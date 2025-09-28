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
FILTER_DRIVERS = os.environ.get("FILTER_DRIVERS", "0") == "1"

RACER_HISTORY_URL = BASE + "/sp_center/RacerHistory.aspx?CustID={cust}"
HEAT_DETAILS_URL = BASE + "/sp_center/HeatDetails.aspx?HeatNo={heat}"

OUT_PATH = os.path.join("data", "leaderboard.json")
HEATS_TXT = os.path.join("data", "heats.txt")
DRIVERS_CSV = os.path.join("data", "drivers.csv")

HEADERS = {
    "User-Agent": "clubspeed-leaderboard/1.2 (+github actions)"
}

# ----------------------------
# Helpers
# ----------------------------

def fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text

def parse_us_datetime_to_date(text: str) -> Optional[dt.datetime]:
    m = re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)', text, flags=re.I)
    if m:
        try:
            return dt.datetime.strptime(
                f"{m.group(1)} {m.group(2).upper().replace(' ', '')}",
                "%m/%d/%Y %I:%M%p"
            )
        except ValueError:
            pass
    m2 = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', text)
    if m2:
        try:
            d = dt.datetime.strptime(m2.group(1), "%m/%d/%Y")
            return d.replace(hour=12, minute=0)
        except ValueError:
            pass
    return None

def extract_heatnos_from_history(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    heats, seen = [], set()
    for a in soup.find_all("a", href=True):
        m = re.search(r"HeatNo=(\d+)", a["href"])
        if m:
            h = m.group(1)
            if h not in seen:
                seen.add(h)
                heats.append(h)
    return heats

def read_driver_filter() -> Optional[List[str]]:
    if not FILTER_DRIVERS or not os.path.exists(DRIVERS_CSV):
        return None
    names = []
    with open(DRIVERS_CSV, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if name:
                names.append(name.lower())
    return names or None

def parse_best_laps_by_racer_from_heat(html: str) -> List[Tuple[str, float]]:
    """
    Parse 'Lap Times by Racer' and return [(racer_name, best_lap_seconds)].
    """
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    m = re.search(r"Lap Times by Racer\s*(.*)", text, flags=re.S)
    if not m:
        return []
    lines, results, i = m.group(1).splitlines(), {}, 0
    while i < len(lines):
        if i + 1 < len(lines) and re.match(r"\(Penalties:\s*\d+\)", lines[i + 1]):
            racer, i, lap_times = lines[i].strip(), i + 2, []
            while i < len(lines):
                if i + 1 < len(lines) and re.match(r"\(Penalties:\s*\d+\)", lines[i + 1]):
                    break
                mm = re.search(r"(\d+\.\d+)", lines[i])
                if mm:
                    lap_times.append(float(mm.group(1)))
                i += 1
            if lap_times:
                results[racer] = min(lap_times)
        else:
            i += 1
    return [(r, v) for r, v in results.items()]

def get_heat_datetime(html: str) -> Optional[dt.datetime]:
    return parse_us_datetime_to_date(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))

def aggregate_best_across_heats(heat_nos: List[str], allowed_names_lower: Optional[List[str]]) -> Dict:
    leaderboard = {}
    for idx, heat in enumerate(heat_nos, 1):
        try:
            heat_html = fetch(HEAT_DETAILS_URL.format(heat=heat))
        except Exception as e:
            print(f"[warn] failed to fetch heat {heat}: {e}")
            continue
        heat_dt = get_heat_datetime(heat_html)
        if not heat_dt or heat_dt.year < START_YEAR:
            continue
        for name, best in parse_best_laps_by_racer_from_heat(heat_html):
            if allowed_names_lower and name.lower() not in allowed_names_lower:
                continue
            cur = leaderboard.get(name)
            if cur is None or best < cur["best_lap_seconds"]:
                leaderboard[name] = {
                    "name": name,
                    "best_lap_seconds": best,
                    "best_heat_no": heat,
                    "best_lap_datetime": heat_dt.replace(microsecond=0).isoformat(),
                }
        time.sleep(0.5)
        if idx % 10 == 0:
            print(f"[info] processed {idx}/{len(heat_nos)} heats")
    return {
        "last_updated_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "source": BASE,
        "racers": sorted(leaderboard.values(), key=lambda r: r["best_lap_seconds"]),
    }

def main():
    if not CUST_ID:
        raise SystemExit("CUST_ID environment variable is required")
    allowed_names_lower = read_driver_filter()
    if os.path.exists(HEATS_TXT):
        with open(HEATS_TXT, "r", encoding="utf-8") as f:
            heat_nos = [ln.strip() for ln in f if ln.strip().isdigit()]
        print(f"[info] Using {len(heat_nos)} heats from heats.txt (filtering year ≥ {START_YEAR})")
    else:
        history_html = fetch(RACER_HISTORY_URL.format(cust=CUST_ID))
        heat_nos = extract_heatnos_from_history(history_html)
        print(f"[info] Found {len(heat_nos)} heats (filtering year ≥ {START_YEAR})")
    result = aggregate_best_across_heats(heat_nos, allowed_names_lower)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"[info] Wrote {OUT_PATH} with {len(result['racers'])} racers (year ≥ {START_YEAR})")

if __name__ == "__main__":
    main()
