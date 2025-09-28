import os
import re
import csv
import time
import datetime as dt
from typing import Dict, List, Tuple, Optional
import requests
from bs4 import BeautifulSoup

# ----------------------------
# Config (env vars)
# ----------------------------
BASE = os.environ.get("SITE_BASE_URL", "https://pgpkent.clubspeedtiming.com").rstrip("/")
START_YEAR = int(os.environ.get("START_YEAR", "2025"))  # only 2025+ by default

RACER_HISTORY_URL = BASE + "/sp_center/RacerHistory.aspx?CustID={cust}"
HEAT_DETAILS_URL = BASE + "/sp_center/HeatDetails.aspx?HeatNo={heat}"

DRIVERS_CSV = os.path.join("data", "drivers.csv")
OUT_CSV = os.path.join("data", "all_laps.csv")

HEADERS = {
    "User-Agent": "clubspeed-alllaps/1.0 (+github actions)"
}

# ----------------------------
# Helpers
# ----------------------------

def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text

def parse_us_datetime(text: str) -> Optional[dt.datetime]:
    """
    Parse 'MM/DD/YYYY hh:mm AM/PM' or 'MM/DD/YYYY' from blob of text (UTC-naive).
    """
    m = re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s*[AP]M)', text, flags=re.I)
    if m:
        s = f"{m.group(1)} {m.group(2).upper().replace(' ', '')}"
        try:
            return dt.datetime.strptime(s, "%m/%d/%Y %I:%M%p")
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
    """
    Return all HeatNo values linked anywhere on a RacerHistory page (order preserved, de-duped).
    """
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

def heat_datetime_from_html(html: str) -> Optional[dt.datetime]:
    soup = BeautifulSoup(html, "html.parser")
    return parse_us_datetime(soup.get_text(" ", strip=True))

def map_custid_to_name_in_heat(html: str) -> Dict[str, str]:
    """
    On the HeatDetails page, standings table links each racer name to their RacerHistory (CustID).
    Build a map: { CustID (encoded) -> Display Name in this heat }.
    """
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
    Parse the 'Lap Times by Racer' section into:
      { racer_name : [(lap_num, lap_seconds), ...] }
    """
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    m = re.search(r"Lap Times by Racer\s*(.*)", text, flags=re.S)
    if not m:
        return {}
    lines = m.group(1).splitlines()

    result: Dict[str, List[Tuple[int, float]]] = {}
    i = 0
    while i < len(lines):
        # Racer header: <Name> then "(Penalties: N)"
        if i + 1 < len(lines) and re.match(r"\(Penalties:\s*\d+\)", lines[i + 1]):
            racer = lines[i].strip()
            i += 2
            laps: List[Tuple[int, float]] = []
            while i < len(lines):
                # Next racer block?
                if i + 1 < len(lines) and re.match(r"\(Penalties:\s*\d+\)", lines[i + 1]):
                    break
                # Typical lap line looks like: "1 81.232 [2]" or "12 80.123"
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
    """
    drivers.csv lines: Name,ID
    Returns list of (name, id) with whitespace trimmed. Skips empty/invalid lines.
    """
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

# ----------------------------
# Main
# ----------------------------

def main():
    drivers = read_drivers_csv(DRIVERS_CSV)
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)

    # Prepare CSV writer (append overwrite)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["driver_name", "driver_id", "heat_no", "heat_datetime_iso", "lap_number", "lap_seconds"])

        for (driver_name, driver_id) in drivers:
            # 1) Get all heats for this driver
            try:
                hist_html = fetch(RACER_HISTORY_URL.format(cust=driver_id))
            except Exception as e:
                print(f"[warn] history fetch failed for {driver_name} ({driver_id}): {e}")
                continue

            heat_nos = extract_heatnos_from_history(hist_html)
            print(f"[info] {driver_name}: found {len(heat_nos)} heats on history page")

            # 2) Visit each heat, filter by date, and grab this driver's laps
            for idx, heat in enumerate(heat_nos, 1):
                # politeness gap every request
                time.sleep(0.5)

                try:
                    heat_html = fetch(HEAT_DETAILS_URL.format(heat=heat))
                except Exception as e:
                    print(f"[warn] heat fetch failed {heat}: {e}")
                    continue

                heat_dt = heat_datetime_from_html(heat_html)
                if not heat_dt or heat_dt.year < START_YEAR:
                    continue

                # Map CustID -> Name for participants in THIS heat
                id_to_name = map_custid_to_name_in_heat(heat_html)
                # Actual display name for this driver in this heat (may differ in spacing/caps)
                display_name = id_to_name.get(driver_id, driver_name)

                # Parse all laps by all racers in this heat
                racer_laps = parse_laps_by_racer_block(heat_html)

                # The "Lap Times by Racer" block is keyed by display name; match case-insensitively
                # Prefer exact match first; fall back to casefold matching
                laps = racer_laps.get(display_name)
                if laps is None:
                    # try case-insensitive lookup
                    lower_map = {k.casefold(): k for k in racer_laps.keys()}
                    key = lower_map.get(display_name.casefold())
                    if key:
                        laps = racer_laps.get(key)

                if not laps:
                    # If we didn't find by name, skip silently (could be DNS/caching or heat not containing this driver)
                    continue

                # Write all laps for this driver in this heat
                iso = heat_dt.replace(microsecond=0).isoformat()
                for lap_num, lap_sec in laps:
                    w.writerow([display_name, driver_id, heat, iso, lap_num, lap_sec])

                if idx % 10 == 0:
                    print(f"[info] {driver_name}: processed {idx}/{len(heat_nos)} heats")

    print(f"[info] Wrote {OUT_CSV}")

if __name__ == "__main__":
    main()
