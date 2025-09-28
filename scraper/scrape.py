import os
import re
import json
import time
import math
import datetime as dt
from typing import Dict, List, Tuple, Optional
import requests
from bs4 import BeautifulSoup

BASE = os.environ.get("SITE_BASE_URL", "https://pgpkent.clubspeedtiming.com").rstrip("/")
CUST_ID = os.environ.get("CUST_ID")  # REQUIRED
YEARS_ENV = os.environ.get("YEARS", "")

RACER_HISTORY_URL = BASE + "/sp_center/RacerHistory.aspx?CustID={cust}"
HEAT_DETAILS_URL = BASE + "/sp_center/HeatDetails.aspx?HeatNo={heat}"

OUT_PATH = os.path.join("data", "leaderboard.json")
HEATS_TXT = os.path.join("data", "heats.txt")

HEADERS = {
    "User-Agent": "clubspeed-leaderboard/1.0 (+github actions)"
}

def get_years() -> List[int]:
    if YEARS_ENV.strip():
        ys = []
        for tok in YEARS_ENV.split(","):
            tok = tok.strip()
            if tok.isdigit():
                ys.append(int(tok))
        return ys
    # default: current year and previous year
    now = dt.datetime.utcnow().year
    return [now, now - 1]

def fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text

def extract_heat_links_from_history(html: str, years: List[int]) -> List[Tuple[str, Optional[str]]]:
    """Return list of (heat_no, iso_datetime_utc?)."""
    soup = BeautifulSoup(html, "html.parser")
    heats: List[Tuple[str, Optional[str]]] = []

    # Look for links to HeatDetails with HeatNo query param
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "HeatDetails.aspx" in href and "HeatNo=" in href:
            m = re.search(r"HeatNo=(\d+)", href)
            if not m:
                continue
            heat_no = m.group(1)
            # Try to find a nearby datetime text (the link text or surrounding cells often include the date/time)
            dt_text = a.get_text(strip=True)
            iso = None
            # If link text isn't a date, check parent row
            row = a.find_parent("tr")
            text_blob = ""
            if row:
                text_blob = row.get_text(" ", strip=True)
            candidate = dt_text if dt_text else text_blob
            # very permissive date parsing: look for yyyy or mm/dd/yyyy etc., but keep simple
            y_found = None
            for y in years:
                if str(y) in candidate:
                    y_found = y
                    break
            if y_found is not None:
                # this heat likely belongs to the target year set
                heats.append((heat_no, None))
    # Dedup while preserving order
    seen = set()
    deduped = []
    for h, t in heats:
        if h not in seen:
            seen.add(h)
            deduped.append((h, t))
    return deduped

def discover_heats_from_history(cust_id: str, years: List[int]) -> List[str]:
    url = RACER_HISTORY_URL.format(cust=cust_id)
    html = fetch(url)
    pairs = extract_heat_links_from_history(html, years)
    return [h for h, _ in pairs]

def parse_best_laps_by_racer_from_heat(html: str) -> List[Tuple[str, float, str, Optional[str]]]:
    """
    Return list of tuples: (racer_name, best_lap_seconds, best_kart, best_lap_iso_utc?)
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    # Favor the "Lap Times by Racer" block (more reliable across skins)
    m = re.search(r"Lap Times by Racer\s*(.*)", text, flags=re.S)
    if not m:
        return []
    section = m.group(1)
    lines = section.splitlines()
    results: Dict[str, Tuple[float, str]] = {}

    i = 0
    while i < len(lines):
        if i + 1 < len(lines) and re.match(r"\(Penalties:\s*\d+\)", lines[i + 1]):
            racer = lines[i].strip()
            i += 2
            lap_times = []
            while i < len(lines):
                if i + 1 < len(lines) and re.match(r"\(Penalties:\s*\d+\)", lines[i + 1]):
                    break
                mline = re.search(r"(\d+\.\d+)\s*\[(\d+)\]", lines[i])
                if mline:
                    lap_time = float(mline.group(1))
                    kart_num = mline.group(2)
                    lap_times.append((lap_time, kart_num))
                i += 1
            if lap_times:
                best_lap, kart = min(lap_times, key=lambda x: x[0])
                results[racer] = (best_lap, kart)
        else:
            i += 1

    return [(r, v[0], v[1], None) for r, v in results.items()]

def aggregate_best_across_heats(heat_nos: List[str]) -> Dict:
    leaderboard: Dict[str, Dict] = {}
    for heat in heat_nos:
        try:
            html = fetch(HEAT_DETAILS_URL.format(heat=heat))
        except Exception as e:
            print(f"[warn] failed to fetch heat {heat}: {e}")
            continue
        racers = parse_best_laps_by_racer_from_heat(html)
        for name, best, kart, iso in racers:
            cur = leaderboard.get(name)
            if (cur is None) or (best < cur["best_lap_seconds"]):
                leaderboard[name] = {
                    "name": name,
                    "best_lap_seconds": best,
                    "best_kart": kart,
                    "best_heat_no": heat,
                    "best_lap_datetime": iso,  # unknown, left as None
                }
        time.sleep(0.5)  # be polite
    out = {
        "last_updated_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "source": BASE,
        "racers": sorted(leaderboard.values(), key=lambda r: r["best_lap_seconds"])
    }
    return out

def main():
    if not CUST_ID:
        raise SystemExit("CUST_ID environment variable is required")
    years = get_years()

    # Determine heat list
    heat_nos: List[str] = []
    if os.path.exists(HEATS_TXT):
        with open(HEATS_TXT, "r", encoding="utf-8") as f:
            heat_nos = [ln.strip() for ln in f if ln.strip().isdigit()]
        print(f"Using {len(heat_nos)} heats from {HEATS_TXT}")
    else:
        heat_nos = discover_heats_from_history(CUST_ID, years)
        print(f"Discovered {len(heat_nos)} heats from RacerHistory ({years})")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    result = aggregate_best_across_heats(heat_nos)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Wrote {OUT_PATH} with {len(result['racers'])} racers")

if __name__ == "__main__":
    main()
