import os
import re
import csv
import time
import datetime as dt
from typing import Dict, List, Tuple, Optional
import requests
from bs4 import BeautifulSoup

BASE = os.environ.get("SITE_BASE_URL", "https://pgpkent.clubspeedtiming.com").rstrip("/")
START_YEAR = int(os.environ.get("START_YEAR", "2025"))  # only 2025+ by default
DEBUG = os.environ.get("DEBUG", "0") == "1"

RACER_HISTORY_URL = BASE + "/sp_center/RacerHistory.aspx?CustID={cust}"
HEAT_DETAILS_URL = BASE + "/sp_center/HeatDetails.aspx?HeatNo={heat}"

DRIVERS_CSV = os.path.join("data", "drivers.csv")
OUT_CSV = os.path.join("data", "all_laps.csv")

HEADERS = {"User-Agent": "clubspeed-alllaps/1.1 (+github actions)"}

def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text

# ---------- DATE PARSING ----------
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"

def parse_us_datetime(text: str) -> Optional[dt.datetime]:
    t = " ".join(text.split())  # normalize whitespace

    # Pattern 1: 9/27/2025 12:45 PM   or 9/27/2025 12:45:30 PM
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*([AP]M)", t, flags=re.I)
    if m:
        date_part, time_part, ampm = m.group(1), m.group(2), m.group(3).upper()
        fmt = "%m/%d/%Y %I:%M%p" if len(time_part.split(":")) == 2 else "%m/%d/%Y %I:%M:%S%p"
        try:
            return dt.datetime.strptime(f"{date_part} {time_part}{ampm}", fmt)
        except ValueError:
            pass

    # Pattern 2: Sep 27, 2025 12:45 PM  (optionally with :ss)
    m = re.search(rf"(({MONTHS})\s+\d{{1,2}},\s*\d{{4}})\s+(\d{{1,2}}:\d{{2}}(?::\d{{2}})?)\s*([AP]M)", t, flags=re.I)
    if m:
        date_part, time_part, ampm = m.group(1), m.group(3), m.group(4).upper()
        fmt = "%b %d, %Y %I:%M%p" if len(time_part.split(":")) == 2 else "%b %d, %Y %I:%M:%S%p"
        try:
            return dt.datetime.strptime(f"{date_part} {time_part}{ampm}", fmt)
        except ValueError:
            pass

    # Pattern 3: bare date 9/27/2025 (assume noon)
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", t)
    if m:
        try:
            d = dt.datetime.strptime(m.group(1), "%m/%d/%Y")
            return d.replace(hour=12, minute=0)
        except ValueError:
            pass

    return None

def heat_datetime_from_html(html: str) -> Optional[dt.datetime]:
    soup = BeautifulSoup(html, "html.parser")
    txt = soup.get_text(" ", strip=True)
    return parse_us_datetime(txt)

# ---------- HEAT & NAME UTILS ----------
def extract_heatnos_from_history(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen, heats = set(), []
    for a in soup.find_all("a", href=True):
        m = re.search(r"HeatNo=(\d+)", a["href"])
        if m:
            h = m.group(1)
            if h not in seen:
                seen.add(h)
                heats.append(h)
    return heats

def map_custid_to_name_in_heat(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    mapping = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "RacerHistory.aspx" in href and "CustID=" in href:
            m = re.search(r"CustID=([^&\s]+)", href)
            if m:
                cust = m.group(1)
                name = a.get_text(strip=True)
                if name:
                    mapping[cust] = name
    return mapping

def parse_laps_by_racer_block(html: str) -> Dict[str, List[Tuple[int, float]]]:
    """
    Return { racer_name : [(lap_num, lap_seconds), ...] }
    """
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    m = re.search(r"Lap Times by Racer\s*(.*)", text, flags=re.S)
    if not m:
        return {}
    lines = m.group(1).splitlines()
    result: Dict[str, List[Tuple[int, float]]] = {}
    i = 0
    while i < len(lines):
        if i + 1 < len(lines) and re.match(r"\(Penalties:\s*\d+\)", lines[i + 1]):
            racer = lines[i].strip()
            i += 2
            laps: List[Tuple[int, float]] = []
            while i < len(lines):
                if i + 1 < len(lines) and re.match(r"\(Penalties:\s*\d+\)", lines[i + 1]):
                    break
                lapm = re.match(r"\s*(\d+)\s+(\d+\.\d+)", lines[i])
                if lapm:
                    laps.append((int(lapm.group(1)), float(lapm.group(2))))
                i += 1
            if laps:
                result[racer] = laps
        else:
            i += 1
    return result

def read_drivers_csv(path: str) -> List[Tuple[str, str]]:
    if not os.path.exists(path):
        raise SystemExit(f"Missing {path}. Expected 'Name,ID' per line.")
    out: List[Tuple[str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            out.append((parts[0], parts[1]))
    return out

def norm(s: str) -> str:
    """normalize for comparison: casefold + collapse spaces"""
    return " ".join((s or "").split()).casefold()

# ---------- MAIN ----------
def main():
    drivers = read_drivers_csv(DRIVERS_CSV)
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["driver_name", "driver_id", "heat_no", "heat_datetime_iso", "lap_number", "lap_seconds"])

        for (driver_name, driver_id) in drivers:
            try:
                hist_html = fetch(RACER_HISTORY_URL.format(cust=driver_id))
            except Exception as e:
                print(f"[warn] history fetch failed for {driver_name} ({driver_id}): {e}")
                continue

            heat_nos = extract_heatnos_from_history(hist_html)
            print(f"[info] {driver_name}: found {len(heat_nos)} heats on history page")

            for idx, heat in enumerate(heat_nos, 1):
                time.sleep(0.5)
                try:
                    heat_html = fetch(HEAT_DETAILS_URL.format(heat=heat))
                except Exception as e:
                    print(f"[warn] heat fetch failed {heat}: {e}")
                    continue

                heat_dt = heat_datetime_from_html(heat_html)
                if not heat_dt:
                    if DEBUG:
                        print(f"[debug] heat {heat}: could not parse date; skipping")
                    continue
                if heat_dt.year < START_YEAR:
                    if DEBUG:
                        print(f"[debug] heat {heat}: {heat_dt.date()} < {START_YEAR}; skip")
                    continue

                id_to_name = map_custid_to_name_in_heat(heat_html)
                racer_laps = parse_laps_by_racer_block(heat_html)

                # Name in laps block might differ slightly; try robust matching
                # Preferred display name based on CustID; fallback to the drivers.csv name
                disp_name = id_to_name.get(driver_id, driver_name)
                laps = racer_laps.get(disp_name)

                if laps is None:
                    # Try case-insensitive, space-collapsed match
                    disp_norm = norm(disp_name)
                    alt = None
                    for k in racer_laps.keys():
                        if norm(k) == disp_norm:
                            alt = k
                            break
                    if alt:
                        laps = racer_laps.get(alt)

                if laps is None:
                    # Final fallback: try startswith match (helps with truncated names)
                    for k in racer_laps.keys():
                        if norm(k).startswith(norm(disp_name)) or norm(disp_name).startswith(norm(k)):
                            laps = racer_laps.get(k)
                            break

                if laps is None:
                    if DEBUG:
                        print(f"[debug] heat {heat}: no laps found for '{driver_name}' (disp='{disp_name}'). "
                              f"Names present: {list(racer_laps.keys())[:5]}...")
                    continue

                iso = heat_dt.replace(microsecond=0).isoformat()
                for lap_num, lap_sec in laps:
                    w.writerow([disp_name, driver_id, heat, iso, lap_num, lap_sec])

                if idx % 10 == 0:
                    print(f"[info] {driver_name}: processed {idx}/{len(heat_nos)} heats")

    print(f"[info] Wrote {OUT_CSV}")

if __name__ == "__main__":
    main()
