from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import config, parse, storage

# ------------------------------------------------------------
# Optional: import clubspeed helper, else provide a fallback
# ------------------------------------------------------------
try:
    from . import clubspeed  # expects clubspeed.heat_details_url(heat_no)
except Exception:
    class _ClubSpeedFallback:
        @staticmethod
        def heat_details_url(heat_no: int) -> str:
            base = getattr(config, "SITE_BASE_URL", "").rstrip("/")
            # Default HeatDetails URL pattern used earlier in this project
            return f"{base}/sp_center/HeatDetails.aspx?HeatNo={heat_no}"
    clubspeed = _ClubSpeedFallback()  # type: ignore


# ------------------------------------------------------------
# HTTP fetching
# ------------------------------------------------------------
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PGPHeatsScraper/1.0; +https://github.com/kevhjel/PGPTimes)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def fetch_html(url: str, *, timeout: float = 20.0, retries: int = 3, backoff: float = 1.5) -> Optional[str]:
    """Fetch a page with simple retry/backoff. Returns text or None on error/non-200."""
    last_exc = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            if resp.status_code == 200 and resp.text:
                return resp.text
            # 404 / empty → treat as miss (no exception)
            return None
        except Exception as e:
            last_exc = e
            time.sleep(backoff ** attempt)
    # final failure
    return None


# ------------------------------------------------------------
# Data validation and helpers
# ------------------------------------------------------------
def _has_heat_data(heat: Dict[str, Any]) -> bool:
    """A heat is considered valid only if it has at least one driver parsed."""
    if not heat:
        return False
    drivers = heat.get("drivers") or []
    return len(drivers) > 0


def _debug_dump_html(heat_no: int, html: str, reason: str = "debug") -> None:
    """Optional: dump raw HTML for inspection when parsing fails."""
    try:
        dbg_dir = os.path.join(config.DATA_DIR, "debug")
        os.makedirs(dbg_dir, exist_ok=True)
        path = os.path.join(dbg_dir, f"{heat_no}_{reason}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass


# ------------------------------------------------------------
# Enrichment: fetch per-driver laps when a link exists (older heats)
# ------------------------------------------------------------
def fetch_driver_laps_if_linked(driver: Dict[str, Any]) -> Dict[str, Any]:
    """If the driver has a 'lap_times_url' and no 'laps', try to fetch and parse it."""
    out = dict(driver)
    if out.get("laps"):
        return out

    link = out.get("lap_times_url")
    if not link:
        return out

    # Build absolute URL if needed
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


# ------------------------------------------------------------
# Scrape a single heat
# ------------------------------------------------------------
def scrape_heat(heat_no: int) -> Optional[Dict[str, Any]]:
    """Scrape one heat. Returns a dict with data, or None if nothing usable was found."""
    url = clubspeed.heat_details_url(heat_no)
    html = fetch_html(url)
    if not html:
        return None

    heat = parse.parse_heat_details_html(html)
    if not heat.get("heat_no"):
        heat["heat_no"] = heat_no

    # Skip excluded heat types entirely
    heat_type = (heat.get("heat_type") or "").strip()
    if config.EXCLUDE_HEAT_TYPES and any(heat_type.lower() == x.lower() for x in config.EXCLUDE_HEAT_TYPES):
        return None

    # Enrich per-driver, if links exist (older non-LapTimesContainer pages)
    enriched = []
    for d in heat.get("drivers", []):
        enriched.append(fetch_driver_laps_if_linked(d))
    heat["drivers"] = enriched
    heat["source_url"] = url

    # If there are no drivers, treat this as a miss (do not write JSON or advance last_heat)
    if not _has_heat_data(heat):
        # Uncomment to keep a debug capture:
        # _debug_dump_html(heat_no, html, "no_drivers")
        return None

    return heat


# ------------------------------------------------------------
# Index rebuild
# ------------------------------------------------------------
def rebuild_driver_index() -> None:
    """
    Build data/driver_index.json from data/heats/*.json.
    The index format:
    {
      "last_updated_utc": "...",
      "drivers": {
        "Name": [
          {
            "heat_no": int,
            "heat_type": str,
            "position": int|null,
            "best_lap_seconds": float|null,
            "laps": [float,...]|null,
            "start_time_iso": str|null
          },
          ...
        ]
      }
    }
    """
    heats_dir = os.path.join(config.DATA_DIR, "heats")
    index: Dict[str, List[Dict[str, Any]]] = {}
    if not os.path.isdir(heats_dir):
        os.makedirs(heats_dir, exist_ok=True)

    for fname in os.listdir(heats_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(heats_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            # skip malformed files
            continue

        heat_no = obj.get("heat_no")
        heat_type = obj.get("heat_type")
        start_time_iso = obj.get("start_time_iso")
        drivers = obj.get("drivers") or []
        if not drivers:
            # skip empties defensively
            continue

        for d in drivers:
            name = (d.get("name") or "").strip()
            if not name:
                continue
            entry = {
                "heat_no": heat_no,
                "heat_type": heat_type,
                "position": d.get("position"),
                "best_lap_seconds": d.get("best_lap_seconds"),
                "laps": d.get("laps"),
                "start_time_iso": start_time_iso,
            }
            index.setdefault(name, []).append(entry)

    out = {
        "last_updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "drivers": index,
    }
    dest = os.path.join(config.DATA_DIR, "driver_index.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------
# CLI / main loop
# ------------------------------------------------------------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PGP heat scraper")
    p.add_argument("start", nargs="?", type=int, help="Optional: start heat number")
    p.add_argument("end", nargs="?", type=int, help="Optional: end heat number (inclusive)")
    p.add_argument("--max", type=int, default=None, help="Max heats to process this run")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    storage.ensure_dirs()
    args = parse_args(argv)

    # Determine starting heat
    last = storage.read_last_heat()
    if args.start is not None:
        cur = args.start
        end = args.end if args.end is not None else args.start
    else:
        # continue from last + 1 if present, else config.START_HEAT_NO
        cur = (last + 1) if isinstance(last, int) else config.START_HEAT_NO
        end = None  # open-ended

    consecutive_misses = 0
    processed = 0

    while True:
        # Bounds
        if end is not None and cur > end:
            break
        if args.max is not None and processed >= args.max:
            break

        heat = scrape_heat(cur)
        if heat is None:
            consecutive_misses += 1
            if consecutive_misses >= config.MAX_CONSECUTIVE_MISSES:
                # assume we've gone past latest existing heat
                break
        else:
            consecutive_misses = 0
            # Persist only valid heats
            storage.write_heat(cur, heat)
            storage.write_last_heat(cur)
            processed += 1

        cur += 1

    # Refresh index from what's actually on disk
    rebuild_driver_index()

    print(f"Done. Processed {processed} heat(s). Last heat: {storage.read_last_heat()}.")


if __name__ == "__main__":
    main()
