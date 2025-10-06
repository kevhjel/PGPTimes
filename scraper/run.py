from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import requests

from . import config, parse, storage

# ---------- Optional URL helper ----------
try:
    from . import clubspeed  # expects clubspeed.heat_details_url(heat_no)
except Exception:
    class _ClubSpeedFallback:
        @staticmethod
        def heat_details_url(heat_no: int) -> str:
            base = getattr(config, "SITE_BASE_URL", "").rstrip("/")
            return f"{base}/sp_center/HeatDetails.aspx?HeatNo={heat_no}"
    clubspeed = _ClubSpeedFallback()  # type: ignore

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PGPHeatsScraper/1.0; +https://github.com/kevhjel/PGPTimes)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def fetch_html(url: str, *, timeout: float = 20.0, retries: int = 3, backoff: float = 1.5) -> Optional[str]:
    """Fetch a page with retry/backoff. Returns text or None on error/non-200."""
    last_exc = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            if resp.status_code == 200 and resp.text:
                return resp.text
            # non-200 or empty is a miss
            return None
        except Exception as e:
            last_exc = e
            time.sleep(backoff ** attempt)
    return None

def _valid_heat(heat: Dict[str, Any]) -> bool:
    """Valid only if at least one driver was parsed."""
    if not heat or not isinstance(heat, dict):
        return False
    drivers = heat.get("drivers") or []
    return isinstance(drivers, list) and len(drivers) > 0

def _enrich_driver_if_linked(d: Dict[str, Any]) -> Dict[str, Any]:
    """If legacy pages expose a per-driver lap popup URL, fetch and merge laps."""
    out = dict(d)
    if out.get("laps"):
        return out
    link = (out.get("lap_times_url") or "").strip()
    if not link:
        return out

    # Make absolute if needed
    if link.startswith("/"):
        base = getattr(config, "SITE_BASE_URL", "").rstrip("/")
        link = base + link
    elif not re.match(r"^https?://", link, re.I):
        base = getattr(config, "SITE_BASE_URL", "").rstrip("/")
        link = f"{base.rstrip('/')}/{link.lstrip('/')}"

    html = fetch_html(link)
    if not html:
        return out

    times, positions = parse.parse_laptimes_popup(html)
    if times:
        out["laps"] = times
    if positions:
        out["lap_positions"] = positions
    return out

def scrape_heat(heat_no: int) -> Optional[Dict[str, Any]]:
    """Scrape a single heat. Return dict or None (on miss/empty/unwanted)."""
    url = clubspeed.heat_details_url(heat_no)
    html = fetch_html(url)
    if not html:
        return None

    # Parse the main HeatDetails page (expects LapTimesContainer if present)
    heat = parse.parse_heat_details_html(html)
    heat["heat_no"] = heat.get("heat_no") or heat_no
    heat["source_url"] = url

    # Optional exclusion by type
    heat_type = (heat.get("heat_type") or "").strip()
    if getattr(config, "EXCLUDE_HEAT_TYPES", None):
        if any(heat_type.lower() == t.lower() for t in config.EXCLUDE_HEAT_TYPES):
            return None

    # Enrich drivers for legacy pages (if they expose lap popups)
    drivers = []
    for d in heat.get("drivers", []) or []:
        drivers.append(_enrich_driver_if_linked(d))
    heat["drivers"] = drivers

    # *** CRITICAL: skip heats with no driver data ***
    if not _valid_heat(heat):
        return None

    return heat

def rebuild_driver_index() -> None:
    """
    Build data/driver_index.json from data/heats/*.json
    {
      "last_updated_utc": "...Z",
      "drivers": {
        "Name": [
          { "heat_no": ..., "heat_type": ..., "position": ..., "best_lap_seconds": ..., "laps": [...], "start_time_iso": ... },
          ...
        ]
      }
    }
    """
    heats_dir = os.path.join(config.DATA_DIR, "heats")
    os.makedirs(heats_dir, exist_ok=True)
    by_name: Dict[str, List[Dict[str, Any]]] = {}

    for root, _, files in os.walk(heats_dir):
        for fn in files:
            if not fn.endswith(".json"):
                continue
            path = os.path.join(root, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    obj = json.load(f)
            except Exception:
                continue
            drivers = obj.get("drivers") or []
            if not drivers:
                continue
            heat_no = obj.get("heat_no")
            heat_type = obj.get("heat_type")
            start_time_iso = obj.get("start_time_iso")
            for d in drivers:
                name = (d.get("name") or "").strip()
                if not name:
                    continue
                by_name.setdefault(name, []).append({
                    "heat_no": heat_no,
                    "heat_type": heat_type,
                    "position": d.get("position"),
                    "best_lap_seconds": d.get("best_lap_seconds"),
                    "laps": d.get("laps"),
                    "start_time_iso": start_time_iso,
                })

    out = {
        "last_updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "drivers": by_name
    }
    dest = os.path.join(config.DATA_DIR, "driver_index.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PGP Heats scraper")
    p.add_argument("start", nargs="?", type=int, help="Optional: start heat number (inclusive)")
    p.add_argument("end", nargs="?", type=int, help="Optional: end heat number (inclusive)")
    p.add_argument("--max", type=int, default=None, help="Max heats to process this run")
    p.add_argument("--force", action="store_true", help="Re-scrape/overwrite existing heat files")
    return p.parse_args(argv)

def main(argv: Optional[List[str]] = None) -> None:
    storage.ensure_dirs()
    args = parse_args(argv)

    # Determine starting point
    last = storage.read_last_heat()
    if args.start is not None:
        cur = args.start
        end = args.end if args.end is not None else args.start
    else:
        cur = (last + 1) if isinstance(last, int) else config.START_HEAT_NO
        end = None

    processed = 0
    consecutive_misses = 0

    while True:
        # stop conditions
        if end is not None and cur > end:
            break
        if args.max is not None and processed >= args.max:
            break

        out_path = storage.heat_path(cur)
        if (not args.force) and os.path.exists(out_path):
            # already scraped — skip ahead without counting as a miss
            print(f"⏭️  {cur} exists, skipping.")
            cur += 1
            continue

        print(f"🔎 Scraping heat {cur} …")
        heat = scrape_heat(cur)

        if heat is None:
            consecutive_misses += 1
            print(f"  … miss ({consecutive_misses} in a row)")
            if consecutive_misses >= config.MAX_CONSECUTIVE_MISSES:
                print("🚧 Reached max consecutive misses; stopping.")
                break
        else:
            consecutive_misses = 0
            # write only valid heats (non-empty drivers)
            storage.write_heat(cur, heat)
            storage.write_last_heat(cur)
            processed += 1
            print(f"✅ Saved {cur} (drivers: {len(heat.get('drivers') or [])})")

        cur += 1

    # Rebuild derived index
    rebuild_driver_index()
    print(f"Done. Wrote {processed} heat(s). Last heat: {storage.read_last_heat()}.")

if __name__ == "__main__":
    main()
