from __future__ import annotations
import sys
import os
import re
from urllib.parse import urljoin
from typing import Dict, Any, List, Optional
from . import config, clubspeed, parse, storage

def fetch_html(url: str) -> Optional[str]:
    resp = clubspeed.get(url)
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        # treat other errors as a miss this round
        return None
    clubspeed.polite_sleep()
    text = resp.text or ""
    # crude guard: if page is extremely short or login page, call it None
    if len(text) < 400 and "Heat" not in text:
        return None
    return text

def normalize_url(href: str) -> str:
    if href.startswith("http"):
        return href
    # Combine against base site
    return urljoin(config.SITE_BASE_URL, href)

def fetch_driver_laps_if_linked(driver: Dict[str, Any]) -> Dict[str, Any]:
    href = driver.get("lap_times_url")
    if not href:
        return driver
    url = normalize_url(href)
    html = fetch_html(url)
    if not html:
        return driver
    times, positions = parse.parse_laptimes_popup(html)
    driver["laps"] = times if times else None
    driver["lap_positions"] = positions
    return driver

def scrape_heat(heat_no: int) -> Optional[Dict[str, Any]]:
    url = clubspeed.heat_details_url(heat_no)
    html = fetch_html(url)
    if not html:
        return None
    heat = parse.parse_heat_details_html(html)
    if not heat.get("heat_no"):
        # If we couldn't parse the number, inject it
        heat["heat_no"] = heat_no
    # filter by heat type if configured
    ht = (heat.get("heat_type") or "").strip()
    if config.EXCLUDE_HEAT_TYPES and any(ht.lower() == x.lower() for x in config.EXCLUDE_HEAT_TYPES):
        return {
            **heat,
            "skipped_reason": f"excluded heat type: {ht}"
        }
    # fetch laps per driver when links exist
    enriched_drivers = []
    for d in heat.get("drivers", []):
        enriched_drivers.append(fetch_driver_laps_if_linked(d))
    heat["drivers"] = enriched_drivers
    heat["source_url"] = url
    return heat

def rebuild_driver_index() -> Dict[str, Any]:
    """
    Scan all heats JSON and build a cross-heat view:
    {
      "last_updated_utc": "...",
      "drivers": {
         "Jane Racer": [
            { "heat_no": 82271, "heat_type": "...", "best_lap_seconds": 81.234, "laps": [..], "position": 1, "kart": "2", "start_time_iso": "..." },
            ...
         ]
      }
    }
    """
    from datetime import datetime, timezone
    summary: Dict[str, List[Dict[str, Any]]] = {}
    heat_nos = storage.list_heat_files()
    for h in heat_nos:
        with open(storage.heat_path(h), "r", encoding="utf-8") as f:
            doc = json.load(f)
        for d in doc.get("drivers", []):
            name = (d.get("name") or "").strip()
            if not name:
                continue
            ent = {
                "heat_no": doc.get("heat_no"),
                "heat_type": doc.get("heat_type"),
                "position": d.get("position"),
                "kart": d.get("kart"),
                "best_lap_seconds": d.get("best_lap_seconds"),
                "laps": d.get("laps"),
                "start_time_iso": doc.get("start_time_iso"),
            }
            summary.setdefault(name, []).append(ent)
    # sort each driver's entries by heat number
    for name, arr in summary.items():
        arr.sort(key=lambda x: (x["start_time_iso"] or "", x["heat_no"] or 0, ))
    driver_index = {
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "drivers": summary,
    }
    storage.write_json(config.DRIVER_INDEX_FILE, driver_index)
    # simple top-level summary
    rollup = {
        "last_updated_utc": driver_index["last_updated_utc"],
        "heats_count": len(heat_nos),
        "max_heat_no": max(heat_nos) if heat_nos else None,
        "source": config.SITE_BASE_URL,
    }
    storage.write_json(config.SUMMARY_FILE, rollup)
    return driver_index

import json

def main():
    storage.ensure_dirs()
    last = storage.read_last_heat()
    start = last + 1 if isinstance(last, int) else config.START_HEAT_NO
    consecutive_misses = 0
    processed = 0

    # You can pass a single heat or a range via CLI (optional)
    #   python -m scraper.run                # continuous from last/START_HEAT_NO
    #   python -m scraper.run 80000 80500    # bounded backfill
    args = sys.argv[1:]
    bounded_start = bounded_end = None
    if len(args) == 1 and args[0].isdigit():
        bounded_start = int(args[0])
        bounded_end = bounded_start
    elif len(args) == 2 and args[0].isdigit() and args[1].isdigit():
        bounded_start = int(args[0])
        bounded_end = int(args[1])

    if bounded_start is not None:
        cur = bounded_start
        end = bounded_end
    else:
        cur = start
        end = None

    while True:
        if end is not None and cur > end:
            break
        heat = scrape_heat(cur)
        if heat is None:
            consecutive_misses += 1
            if consecutive_misses >= config.MAX_CONSECUTIVE_MISSES:
                break
        else:
            consecutive_misses = 0
            storage.write_heat(cur, heat)
            storage.write_last_heat(cur)
            processed += 1
        cur += 1

    rebuild_driver_index()
    print(f"Done. Processed {processed} heat(s). Last heat: {storage.read_last_heat()}.")

if __name__ == "__main__":
    main()
