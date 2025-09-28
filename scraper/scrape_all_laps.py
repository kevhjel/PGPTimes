import os
import re
import csv
import time
import datetime as dt
from typing import Dict, List, Tuple, Optional
import requests
from bs4 import BeautifulSoup, NavigableString, Tag

BASE = os.environ.get("SITE_BASE_URL", "https://pgpkent.clubspeedtiming.com").rstrip("/")
START_YEAR = int(os.environ.get("START_YEAR", "2025"))
DEBUG = os.environ.get("DEBUG", "0") == "1"

RACER_HISTORY_URL = BASE + "/sp_center/RacerHistory.aspx?CustID={cust}"
HEAT_DETAILS_URL = BASE + "/sp_center/HeatDetails.aspx?HeatNo={heat}"

DRIVERS_CSV = os.path.join("data", "drivers.csv")
OUT_CSV = os.path.join("data", "all_laps.csv")

HEADERS = {"User-Agent": "clubspeed-alllaps/1.2 (+github actions)"}

def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text

# ---------- DATE PARSING ----------
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"

def parse_us_datetime(text: str) -> Optional[dt.datetime]:
    t = " ".join(text.split())  # normalize whitespace
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*([AP]M)", t, flags=re.I)
    if m:
        date_part, time_part, ampm = m.group(1), m.group(2), m.group(3).upper()
        fmt = "%m/%d/%Y %I:%M%p" if len(time_part.split(":")) == 2 else "%m/%d/%Y %I:%M:%S%p"
        try:
            return dt.datetime.strptime(f"{date_part} {time_part}{ampm}", fmt)
        except ValueError:
            pass
    m = re.search(rf"(({MONTHS})\s+\d{{1,2}},\s*\d{{4}})\s+(\d{{1,2}}:\d{{2}}(?::\d{{2}})?)\s*([AP]M)", t, flags=re.I)
    if m:
        date_part, time_part, ampm = m.group(1), m.group(3), m.group(4).upper()
        fmt = "%b %d, %Y %I:%M%p" if len(time_part.split(":")) == 2 else "%b %d, %Y %I:%M:%S%p"
        try:
            return dt.datetime.strptime(f"{date_part} {time_part}{ampm}", fmt)
        except ValueError:
            pass
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

def norm(s: str) -> str:
    return " ".join((s or "").split()).casefold()

# ---------- LAPS PARSERS ----------
def parse_laps_text_block(html: str) -> Dict[str, List[Tuple[int, float]]]:
    """
    Original text-based parser of 'Lap Times by Racer'.
    Returns { racer_name : [(lap_num, lap_seconds), ...] }
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

def nearest_preceding_name(node: Tag) -> Optional[str]:
    """
    Walk backward from a table to find a likely racer name nearby:
    look for strong/b/h3/h4/p text that isn't just 'Lap Times by Racer' or penalties.
    """
    stop_after = 10  # walk up to 10 previous elements
    cur = node
    steps = 0
    while cur and steps < stop_after:
        cur = cur.find_previous(string=True)
        steps += 1
        if not cur:
            break
        if isinstance(cur, NavigableString):
            text = cur.strip()
            if not text:
                continue
            if re.search(r"Lap Times by Racer", text, flags=re.I):
                continue
            if re.match(r"\(Penalties:\s*\d+\)", text):
                continue
            # Heuristic: names are shortish and have a space
            if 2 <= len(text.split()) <= 4 and len(text) <= 40:
                return text
    return None

def parse_laps_dom_tables(html: str) -> Dict[str, List[Tuple[int, float]]]:
    """
    Fallback: find per-driver lap tables.
    Look for tables whose first column is Lap # and second column is time (xx.xx).
    Associate table to nearest preceding name-like text.
    """
    soup = BeautifulSoup(html, "html.parser")
    result: Dict[str, List[Tuple[int, float]]] = {}

    tables = soup.find_all("table")
    for tbl in tables:
        # Peek at first 1-2 body rows to see if they look like "lap#, time"
        rows = tbl.find_all("tr")
        if len(rows) < 2:
            continue
        # Skip header if present
        start_idx = 0
        hdr_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if hdr_cells and re.search(r"lap", " ".join(hdr_cells), flags=re.I):
            start_idx = 1

        sample_ok = False
        sample = []
        for r in rows[start_idx:start_idx+2]:
            cells = [c.get_text(strip=True) for c in r.find_all("td")]
            if len(cells) < 2:
                break
            if re.match(r"^\d+$", cells[0]) and re.match(r"^\d+\.\d+$", cells[1]):
                sample_ok = True
                sample.append(cells)
        if not sample_ok:
            continue

        # Looks like a lap table; find all rows as (lap, time)
        laps: List[Tuple[int, float]] = []
        for r in rows[start_idx:]:
            cells = [c.get_text(strip=True) for c in r.find_all("td")]
            if len(cells) < 2:
                continue
            if re.match(r"^\d+$", cells[0]) and re.match(r"^\d+\.\d+$", cells[1]):
                try:
                    laps.append((int(cells[0]), float(cells[1])))
                except ValueError:
                    continue

        if not laps:
            continue

        # Find a name near this table
        candidate_name = nearest_preceding_name(tbl)
        if not candidate_name:
            # couldn't confidently associate; skip
            if DEBUG:
                print("[debug] lap table found but no preceding name detected; skipping this table")
            continue

        # Merge (if multiple tables for same name)
        result.setdefault(candidate_name, []).extend(laps)

    return result

def parse_laps_by_racer_any(html: str) -> Dict[str, List[Tuple[int, float]]]:
    """
    Try text parser first; if empty, try DOM tables.
    """
    d = parse_laps_text_block(html)
    if d:
        return d
    return parse_laps_dom_tables(html)

# ---------- MAIN ----------
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

def main():
    drivers = read_drivers_csv(DRIVERS_CSV)
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)

    w
