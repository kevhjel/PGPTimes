# scraper/scrape_all_laps.py
import os
import re
import csv
import time
import datetime as dt
from typing import Dict, List, Tuple, Optional
import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# ------------------- Config -------------------
BASE = os.environ.get("SITE_BASE_URL", "https://pgpkent.clubspeedtiming.com").rstrip("/")
START_YEAR = int(os.environ.get("START_YEAR", "2025"))
DEBUG = os.environ.get("DEBUG", "0") == "1"

RACER_HISTORY_URL = BASE + "/sp_center/RacerHistory.aspx?CustID={cust}"
HEAT_DETAILS_URL = BASE + "/sp_center/HeatDetails.aspx?HeatNo={heat}"
HEAT_DETAILS_URL_SHOW = BASE + "/sp_center/HeatDetails.aspx?HeatNo={heat}&ShowLapTimes=true"
HEAT_DETAILS_PRINT_URL = BASE + "/sp_center/HeatDetailsPrint.aspx?HeatNo={heat}"

DRIVERS_CSV = os.path.join("data", "drivers.csv")
OUT_CSV = os.path.join("data", "all_laps.csv")

# Pretend to be a normal desktop browser
BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"

# ------------------- HTTP helpers -------------------
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(BASE_HEADERS)
    return s

def fetch(session: requests.Session, url: str) -> str:
    headers = {"Referer": BASE + "/sp_center/"}
    r = session.get(url, headers=headers, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r.text

# ------------------- Date parsing -------------------
def parse_us_datetime(text: str) -> Optional[dt.datetime]:
    t = " ".join(text.split())
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

# ------------------- Utilities -------------------
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

# ------------------- Lap parsers -------------------
def parse_laps_text_block(html: str) -> Dict[str, List[Tuple[int, float]]]:
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
    steps = 0
    cur = node
    while cur and steps < 12:
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
            if 2 <= len(text.split()) <= 4 and len(text) <= 40:
                return text
    return None

def parse_laps_dom_tables(html: str) -> Dict[str, List[Tuple[int, float]]]:
    soup = BeautifulSoup(html, "html.parser")
    result: Dict[str, List[Tuple[int, float]]] = {}
    for tbl in soup.find_all("table"):
        rows = tbl.find_all("tr")
        if len(rows) < 2:
            continue
        start_idx = 0
        hdr_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if hdr_cells and re.search(r"lap", " ".join(hdr_cells), flags=re.I):
            start_idx = 1
        sample_ok = False
        for r in rows[start_idx:start_idx + 2]:
            cells = [c.get_text(strip=True) for c in r.find_all("td")]
            if len(cells) >= 2 and re.match(r"^\d+$", cells[0]) and re.match(r"^\d+\.\d+$", cells[1]):
                sample_ok = True
        if not sample_ok:
            continue
        laps: List[Tuple[int, float]] = []
        for r in rows[start_idx:]:
            cells = [c.get_text(strip=True) for c in r.find_all("td")]
            if len(cells) >= 2 and re.match(r"^\d+$", cells[0]) and re.match(r"^\d+\.\d+$", cells[1]):
                try:
                    laps.append((int(cells[0]), float(cells[1])))
                except ValueError:
                    pass
        if not laps:
            continue
        name = nearest_preceding_name(tbl)
        if not name:
            if DEBUG:
                print("[debug] lap mini-table found but no preceding name; skipping a table")
            continue
        result.setdefault(name, []).extend(laps)
    return result

def parse_global_lap_table(html: str) -> List[Tuple[str, int, float]]:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    candidates = []
    for tbl in tables:
        headers = [th.get_text(strip=True).lower() for th in tbl.find_all("th")]
        if not headers:
            first = tbl.find("tr")
            if first:
                headers = [td.get_text(strip=True).lower() for td in first.find_all("td")]
        if not headers:
            continue
        header_str = " ".join(headers)
        if re.search(r"\blap\b", header_str) and re.search(r"\b(time|best|lap time)\b", header_str) and re.search(r"\b(driver|name)\b", header_str):
            candidates.append(tbl)
    results: List[Tuple[str, int, float]] = []
    for tbl in candidates:
        rows = tbl.find_all("tr")
        start = 1 if rows and rows[0].find_all("th") else 0
        for r in rows[start:]:
            cells = [c.get_text(strip=True) for c in r.find_all("td")]
            if len(cells) < 3:
                continue
            triplets = [
                (cells[0], cells[1], cells[2]),
                (cells[0], cells[2], cells[1]),
                (cells[1], cells[0], cells[2]),
            ]
            parsed = False
            for a, b, c in triplets:
                if re.match(r"^\d+$", a) and re.match(r"^\d+(\.\d+)?$", c) and b:
                    try:
                        results.append((b, int(a), float(c)))
                        parsed = True
                        break
                    except ValueError:
                        pass
            if not parsed:
                ints = [i for i, x in enumerate(cells) if re.match(r"^\d+$", x)]
                floats = [i for i, x in enumerate(cells) if re.match(r"^\d+(\.\d+)?$", x)]
                if ints and floats:
                    try:
                        lap_no = int(cells[ints[0]])
                        lap_sec = float(cells[floats[0]])
                        name_idx = 0
                        while name_idx in (ints[0], floats[0]) and name_idx < len(cells) - 1:
                            name_idx += 1
                        name = cells[name_idx]
                        if name:
                            results.append((name, lap_no, lap_sec))
                    except ValueError:
                        pass
    return results

def parse_laps_by_racer_any(html: str) -> Dict[str, List[Tuple[int, float]]]:
    d = parse_laps_text_block(html)
    if d:
        return d
    d = parse_laps_dom_tables(html)
    if d:
        return d
    rows = parse_global_lap_table(html)
    grouped: Dict[str, List[Tuple[int, float]]] = {}
    for name, lap_no, lap_sec in rows:
        grouped.setdefault(name, []).append((lap_no, lap_sec))
    return grouped

# ------------------- Drivers CSV -------------------
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

# ------------------- Main -------------------
def main():
    session = make_session()
    drivers = read_drivers_csv(DRIVERS_CSV)
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["driver_name", "driver_id", "heat_no", "heat_datetime_iso", "lap_number", "lap_seconds"])

        for (driver_name, driver_id) in drivers:
            # 1) Driver history
            try:
                hist_html = fetch(session, RACER_HISTORY_URL.format(cust=driver_id))
            except Exception as e:
                print(f"[warn] history fetch failed for {driver_name} ({driver_id}): {e}")
                continue

            heat_nos = extract_heatnos_from_history(hist_html)
            print(f"[info] {driver_name}: found {len(heat_nos)} heats on history page")

            # 2) Heats loop
            for idx, heat in enumerate(heat_nos, 1):
                time.sleep(0.5)

                # Try ALL variants, keep the one that yields the most racer sections
                variants = [
                    (HEAT_DETAILS_URL.format(heat=heat), "default"),
                    (HEAT_DETAILS_URL_SHOW.format(heat=heat), "show"),
                    (HEAT_DETAILS_PRINT_URL.format(heat=heat), "print"),
                ]
                best = {"variant": None, "html": None, "racer_laps": {}, "keys": 0}

                for url, tag in variants:
                    try:
                        html = fetch(session, url)
                    except Exception as e:
                        if DEBUG:
                            print(f"[debug] heat {heat}: fetch failed for '{tag}': {e}")
                        continue

                    # Year filter (do early; date should be present in all variants)
                    heat_dt = heat_datetime_from_html(html)
                    if not heat_dt:
                        if DEBUG:
                            print(f"[debug] heat {heat}: could not parse date in '{tag}'; trying next variant")
                        continue
                    if heat_dt.year < START_YEAR:
                        if DEBUG:
                            print(f"[debug] heat {heat}: {heat_dt.date()} < {START_YEAR}; skip whole heat")
                        # Skip the entire heat quickly
                        best = None
                        break

                    # Parse laps immediately
                    laps_by_racer = parse_laps_by_racer_any(html)
                    num_keys = len(laps_by_racer)
                    if DEBUG:
                        print(f"[debug] heat {heat}: variant '{tag}' produced {num_keys} racer sections")

                    # Track the best variant (most racer keys)
                    if num_keys > (best["keys"] if best else -1):
                        best = {"variant": tag, "html": html, "racer_laps": laps_by_racer, "keys": num_keys, "heat_dt": heat_dt}

                if best is None:
                    # filtered out by date in one of the variants
                    continue

                if not best["html"]:
                    if DEBUG:
                        print(f"[debug] heat {heat}: no variant returned usable HTML")
                    continue

                if DEBUG:
                    print(f"[debug] heat {heat}: using variant '{best['variant']}' with {best['keys']} racer sections")

                # Prefer the display name as shown in this heat
                id_to_name = map_custid_to_name_in_heat(best["html"])
                disp_name = id_to_name.get(driver_id, driver_name)

                # Pick laps for this driver
                racer_laps = best["racer_laps"]
                laps = None

                # exact
                if disp_name in racer_laps:
                    laps = racer_laps[disp_name]
                # case/space-insensitive
                if laps is None:
                    disp_norm = norm(disp_name)
                    for k in list(racer_laps.keys()):
                        if norm(k) == disp_norm:
                            laps = racer_laps[k]; break
                # prefix-safe (truncations)
                if laps is None:
                    for k in list(racer_laps.keys()):
                        if norm(k).startswith(norm(disp_name)) or norm(disp_name).startswith(norm(k)):
                            laps = racer_laps[k]; break
                # last-name containment (helps with global-table cases)
                if laps is None and racer_laps:
                    last = (driver_name.strip().split()[-1] if driver_name.strip() else "").casefold()
                    for k in list(racer_laps.keys()):
                        if last and last in norm(k):
                            laps = racer_laps[k]; break

                if laps is None:
                    if DEBUG:
                        keys = list(racer_laps.keys())
                        print(f"[debug] heat {heat}: no laps found for '{driver_name}' (disp='{disp_name}'). Names present: {keys[:10]}...")
                    continue

                if DEBUG:
                    print(f"[debug] heat {heat}: found {len(laps)} laps for {disp_name} (variant={best['variant']})")

                iso = best["heat_dt"].replace(microsecond=0).isoformat()
                with open(OUT_CSV, "a", newline="", encoding="utf-8") as fa:
                    wa = csv.writer(fa)
                    for lap_num, lap_sec in laps:
                        wa.writerow([disp_name, driver_id, heat, iso, lap_num, lap_sec])

                if idx % 10 == 0:
                    print(f"[info] {driver_name}: processed {idx}/{len(heat_nos)} heats")

    print(f"[info] Wrote {OUT_CSV}")

if __name__ == "__main__":
    main()
