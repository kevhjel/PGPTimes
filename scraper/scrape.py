import os
import re
import json
import time
import datetime as dt
from typing import Dict, List, Tuple, Optional
import requests
from bs4 import BeautifulSoup

# ----------------------------
# Config (env vars)
# ----------------------------
BASE = os.environ.get("SITE_BASE_URL", "https://pgpkent.clubspeedtiming.com").rstrip("/")
CUST_ID = os.environ.get("CUST_ID")  # REQUIRED
START_YEAR = int(os.environ.get("START_YEAR", "2025"))  # default: only 2025 and newer
FILTER_DRIVERS = os.environ.get("FILTER_DRIVERS", "0") == "1"  # set to 1 to enable driver filtering

RACER_HISTORY_URL = BASE + "/sp_center/RacerHistory.aspx?CustID={cust}"
HEAT_DETAILS_URL = BASE + "/sp_center/HeatDetails.aspx?HeatNo={heat}"

OUT_PATH = os.path.join("data", "leaderboard.json")
HEATS_TXT = os.path.join("data", "heats.txt")
DRIVERS_CSV = os.path.join("data", "drivers.csv")

HEADERS = {
    "User-Agent": "clubspeed-leaderboard/1.1 (+github actions)"
}

# ----------------------------
# Helpers
# ----------------------------

def fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text

def parse_us_datetime_to_date(text: str) -> Optional[dt.datetime]:
    """
    Try to find a 'MM/DD/YYYY HH:MM AM/PM' or 'MM/DD/YYYY' in the text and return a datetime.
    Returns None if not found.
    """
    # Full datetime first (e.g., 9/27/2025 12:45 PM)
    m = re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)', text, flags=re.I)
    if m:
        date_part, time_part = m.group(1), m.group(2).upper().replace(" ", "")
        # Normalize time like "12:45PM"
        try:
            return dt.datetime.strptime(f"{date_part} {time_part}", "%m/%d/%Y %I:%M%p")
        except ValueError:
            pass

    # Fallback: just the date (use noon)
    m2 = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', text)
    if m2:
        date_part = m2.group(1)
        try:
            d = dt.datetime.strptime(date_part, "%m/%d/%Y")
            return d.replace(hour=12, minute=0)
        except ValueError:
            pass
    return None

def extract_heatnos_from_history(html: str) -> List[str]:
    """
    Return all HeatNo values linked anywhere on the RacerHistory page (order preserved, de-duped).
    """
    soup = BeautifulSoup(html, "html.parser")
    heats: List[str] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        m = re.search(r"HeatNo=(\d+)", a["href"])
        if m:
            h = m.group(1)
            if h not in seen:
                seen.add(h)
                heats.append(h)
    return heats

def read_driver_filter() -> Optional[List[str]]:
    """
    If FILTER_DRIVERS=1 and data/drivers.csv exists, return a lowercase list of allowed driver names.
    Otherwise return None.
    """
    if not FILTER_DRIVERS:
        return None
    if not os.path.exists(DRIVERS_CSV):
        return None
    names: List[str] = []
    with open(DRIVERS_CSV, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if name:
                names.append(name.lower())
    return names or None

def parse_best_laps_by_racer_from_heat(html: str) -> List[Tuple[str, float, str]]:
    """
    Parse 'Lap Times by Racer' section and return [(racer_name, best_lap_seconds, best_kart)].
    We pick the kart associated with the best lap.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    m = re.search(r"Lap Times by Racer\s*(.*)", text, flags=re.S)
    if not m:
        return []
    section = m.group(1)

    lines = section.splitlines()
    results: Dict[str, Tuple[float, str]] = {}

    i = 0
    while i < len(lines):
        # A racer block typically appears as:
        # <Name>
        # (Penalties: N)
        # <Lap#> <time> [kart]
        if i + 1 < len(lines) and re.match(r"\(Penalties:\s*\d+\)", lines[i + 1]):
            racer = lines[i].strip()
            i += 2
            lap_times = []
            while i < len(lines):
                # Next racer block?
                if i + 1 < len(lines) and re.match(r"\(Penalties:\s*\d+\)", lines[i + 1]):
                    break
                # Lap line like: "1 81.232 [2]"
                mm = re.search(r"(\d+\.\d+)\s*\[(\d+)\]", lines[i])
                if mm:
                    lap_time = float(mm.group(1))
                    kart_num = mm.group(2)
                    lap_times.append((lap_time, kart_num))
                i += 1
            if lap_times:
                best_lap, kart = min(lap_times, key=lambda x: x[0])
                results[racer] = (best_lap, kart)
        else:
            i += 1

    return [(r, v[0], v[1]) for r, v in results.items()]

def get_heat_datetime(html: str) -> Optional[dt.datetime]:
    """
    Extract the heat's date/time from the heat details page text.
    """
    soup = BeautifulSoup(html, "html.parser")
    txt = soup.get_text(" ", strip=True)
    return parse_us_datetime_to_date(txt)

def aggregate_best_across_heats(heat_nos: List[str], allowed_names_lower: Optional[List[str]]) -> Dict:
    leaderboard: Dict[str, Dict] = {}

    for idx, heat in enumerate(heat_nos, 1):
        try:
            heat_html = fetch(HEAT_DETAILS_URL.format(heat=heat))
        except Exception as e:
            print(f"[warn] failed to fetch heat {heat}: {e}")
            continue

        # Filter by START_YEAR using the actual heat date on its page
        heat_dt = get_heat_datetime(heat_html)
        if not heat_dt:
            print(f"[info] heat {heat}: no date found, skipping")
            continue
        if heat_dt.year < START_YEAR:
            print(f"[info] heat {heat}: {heat_dt.date()} < {START_YEAR}, skipping")
            continue

        racers = parse_best_laps_by_racer_from_heat(heat_html)

        for name, best, kart in racers:
            if allowed_names_lower is not None:
                if name.lower() not in allowed_names_lower:
                    continue
            cur = leaderboard.get(name)
            if (cur is None) or (best < cur["best_lap_seconds"]):
                leaderboard[name] = {
                    "name": name,
                    "best_lap_seconds": best,
                    "best_heat_no": heat,
                    # Store ISO in UTC-naive (site has no tz)—we keep what we parsed
                    "best_lap_datetime": heat_dt.replace(microsecond=0).isoformat() if heat_dt else None,
                }

        # Be polite to the site
        time.sleep(0.5)

        if idx % 10 == 0:
            print(f"[info] processed {idx}/{len(heat_nos)} heats")

    out = {
        "last_updated_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "source": BASE,
        "racers": sorted(leaderboard.values(), key=lambda r: r["best_lap_seconds"])
    }
    return out

def main():
    if not CUST_ID:
        raise SystemExit("CUST_ID environment variable is required")

    # Load allowed driver list if requested
    allowed_names_lower = read_driver_filter()

    # Determine heat list
    if os.path.exists(HEATS_TXT):
        with open(HEATS_TXT, "r", encoding="utf-8") as f:
            heat_nos = [ln.strip() for ln in f if ln.strip().isdigit()]
        print(f"[info] Using {len(heat_nos)} heats from {HEATS_TXT} (will filter by year ≥ {START_YEAR})")
    else:
        history_html = fetch(RACER_HISTORY_URL.format(cust=CUST_ID))
        all_heats = extract_heatnos_from_history(history_html)
        print(f"[info] Discovered {len(all_heats)} heats on RacerHistory page (will filter by year ≥ {START_YEAR})")
        heat_nos = all_heats

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    result = aggregate_best_across_heats(heat_nos, allowed_names_lower)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"[info] Wrote {OUT_PATH} with {len(result['racers'])} racers (year ≥ {START_YEAR})")

if __name__ == "__main__":
    main()
