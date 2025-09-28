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

# control how many debug HTML files we dump per driver
DEBUG_MAX_DUMPS = int(os.environ.get("DEBUG_MAX_DUMPS", "6"))
# which variants to dump (comma-separated from {"default","show","print"})
DEBUG_DUMP_VARIANTS = set(
    v.strip().lower() for v in os.environ.get("DEBUG_DUMP_VARIANTS", "default,print").split(",")
    if v.strip()
)

RACER_HISTORY_URL = BASE + "/sp_center/RacerHistory.aspx?CustID={cust}"
HEAT_DETAILS_URL = BASE + "/sp_center/HeatDetails.aspx?HeatNo={heat}"
HEAT_DETAILS_URL_SHOW = BASE + "/sp_center/HeatDetails.aspx?HeatNo={heat}&ShowLapTimes=true"
HEAT_DETAILS_PRINT_URL = BASE + "/sp_center/HeatDetailsPrint.aspx?HeatNo={heat}"

DRIVERS_CSV = os.path.join("data", "drivers.csv")
OUT_CSV = os.path.join("data", "all_laps.csv")
DEBUG_DIR = os.path.join("data", "debug_html")

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
    # e.g., 9/27/2025 12:45 PM  or  9/27/2025 12:45:30 PM
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*([AP]M)", t, flags=re.I)
    if m:
        date_part, time_part, ampm = m.group(1), m.group(2), m.group(3).upper()
        fmt = "%m/%d/%Y %I:%M%p" if len(time_part.split(":")) == 2 else "%m/%d/%Y %I:%M:%S%p"
        try:
            return dt.datetime.strptime(f"{date_part} {time_part}{ampm}", fmt)
        except ValueError:
            pass
    # e.g., Sep 27, 2025 12:45 PM
    m = re.search(rf"(({MONTHS})\s+\d{{1,2}},\s*\d{{4}})\s+(\d{{1,2}}:\d{{2}}(?::\d{{2}})?)\s*([AP]M)", t, flags=re.I)
    if m:
        date_part, time_part, ampm = m.group(1), m.group(3), m.group(4).upper()
        fmt = "%b %d, %Y %I:%M%p" if len(time_part.split(":")) == 2 else "%b %d, %Y %I:%M:%S%p"
        try:
            return dt.datetime.strptime(f"{date_part} {time_part}{ampm}", fmt)
        except ValueError:
            pass
    # bare date -> assume noon
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

def map_heat_dates_from_history(html: str) -> Dict[str, dt.datetime]:
    """
    Build heat_no -> datetime map by walking table rows in RacerHistory.
    """
    soup = BeautifulSoup(html, "html.parser")
    heat_dates: Dict[str, dt.datetime] = {}
    for a in soup.find_all("a", href=True):
        m = re.search(r"HeatNo=(\d+)", a["href"])
        if not m:
            continue
        heat = m.group(1)
        row = a.find_parent("tr")
        if row:
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            for c in cells:
                d = parse_us_datetime(c)
                if d:
                    heat_dates[heat] = d
                    break
        if heat not in heat_dates:
            t = a.get_text(" ", strip=True) + " " + (row.get_text(" ", strip=True) if row else "")
            d = parse_us_datetime(t)
            if d:
                heat_dates[heat] = d
    return heat_dates

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

# ------------------- Debug HTML dump -------------------
def dump_debug_html(heat: str, tag: str, html: str, driver_key: str, per_driver_counter: Dict[str, int]):
    """
    Save fetched HTML under data/debug_html/ if DEBUG is on and cap per driver.
    """
    if not DEBUG:
        return
    if tag.lower() not in DEBUG_DUMP_VARIANTS:
        return
    os.makedirs(DEBUG_DIR, exist_ok=True)
    count = per_driver_counter.get(driver_key, 0)
    if count >= DEBUG_MAX_DUMPS:
        return
    fname = f"{heat}_{tag.lower()}.html"
    path = os.path.join(DEBUG_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    per_driver_counter[driver_key] = count + 1
    print(f"[debug] wrote {path}")

# ------------------- Lap parsers -------------------
def parse_laps_text_block(html: str) -> Dict[str, List[Tuple[int, float]]]:
    """
    Parse 'Lap Times by Racer' plain-text section from full-page text.
    """
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    m = re.search(r"Lap\s*Times\s*by\s*Racer\s*(.*)", text, flags=re.I | re.S)
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
                lapm = re.match(r"\s*(\d+)\s+(\d+(?:\.\d+)?)", lines[i])
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
    For per-driver mini tables, look backwards for a nearby name line.
    """
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
            if re.search(r"Lap\s*Times\s*by\s*Racer", text, flags=re.I):
                continue
            if re.match(r"\(Penalties:\s*\d+\)", text):
                continue
            if 2 <= len(text.split()) <= 4 and len(text) <= 40:
                return text
    return None

def parse_laps_dom_tables(html: str) -> Dict[str, List[Tuple[int, float]]]:
    """
    Fallback: per-driver mini tables (two columns Lap/Time).
    """
    soup = BeautifulSoup(html, "html.parser")
    result: Dict[str, List[Tuple[int, float]]] = {}
    for tbl in soup.find_all("table"):
        rows = tbl.find_all("tr")
        if len(rows) < 2:
            continue
        start_idx = 0
        hdr_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if hdr_cells and re.search(r"\blap\b", " ".join(hdr_cells), flags=re.I):
            start_idx = 1
        sample_ok = False
        for r in rows[start_idx:start_idx + 2]:
            cells = [c.get_text(strip=True) for c in r.find_all("td")]
            if len(cells) >= 2 and re.match(r"^\d+$", cells[0]) and re.match(r"^\d+(?:\.\d+)?$", cells[1]):
                sample_ok = True
        if not sample_ok:
            continue
        laps: List[Tuple[int, float]] = []
        for r in rows[start_idx:]:
            cells = [c.get_text(strip=True) for c in r.find_all("td")]
            if len(cells) >= 2 and re.match(r"^\d+$", cells[0]) and re.match(r"^\d+(?:\.\d+)?$", cells[1]):
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

def parse_laps_pre_text(html: str) -> Dict[str, List[Tuple[int, float]]]:
    """
    Some print variants render the section inside <pre>. Parse that plain text.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: Dict[str, List[Tuple[int, float]]] = {}
    pre_texts = []
    for pre in soup.find_all("pre"):
        t = pre.get_text("\n", strip=True)
        if t:
            pre_texts.append(t)
    if not pre_texts:
        return out
    text = "\n".join(pre_texts)
    m = re.search(r"Lap\s*Times\s*by\s*Racer\s*(.*)", text, flags=re.I | re.S)
    block_src = m.group(1) if m else text
    lines = block_src.splitlines()
    i = 0
    while i < len(lines):
        if i + 1 < len(lines) and re.match(r"\(Penalties:\s*\d+\)", lines[i + 1]):
            name = lines[i].strip()
            i += 2
            laps: List[Tuple[int, float]] = []
            while i < len(lines):
                if i + 1 < len(lines) and re.match(r"\(Penalties:\s*\d+\)", lines[i + 1]):
                    break
                mrow = re.match(r"\s*(\d+)\s+(\d+(?:\.\d+)?)", lines[i])
                if mrow:
                    laps.append((int(mrow.group(1)), float(mrow.group(2))))
                i += 1
            if laps:
                out.setdefault(name, []).extend(laps)
        else:
            i += 1
    return out

def parse_global_lap_table(html: str) -> List[Tuple[str, int, float]]:
    """
    Last resort: a single global table with Lap | Driver/Name | Time. Return rows to group later.
    """
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
                if re.match(r"^\d+$", a) and re.match(r"^\d+(?:\.\d+)?$", c) and b:
                    try:
                        results.append((b, int(a), float(c)))
                        parsed = True
                        break
                    except ValueError:
                        pass
            if not parsed:
                ints = [i for i, x in enumerate(cells) if re.match(r"^\d+$", x)]
                floats = [i for i, x in enumerate(cells) if re.match(r"^\d+(?:\.\d+)?$", x)]
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
    """
    Try multiple strategies and return { name : [(lap_no, lap_sec), ...] }.
    """
    d = parse_laps_text_block(html)
    if d:
        return d
    d = parse_laps_dom_tables(html)
    if d:
        return d
    d = parse_laps_pre_text(html)
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

    # fresh write
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["driver_name", "driver_id", "heat_no", "heat_datetime_iso", "lap_number", "lap_seconds"])

    for (driver_name, driver_id) in drivers:
        # cap debug dumps per driver
        debug_counter: Dict[str, int] = {}

        # history + heat date map
        try:
            hist_html = fetch(session, RACER_HISTORY_URL.format(cust=driver_id))
        except Exception as e:
            print(f"[warn] history fetch failed for {driver_name} ({driver_id}): {e}")
            continue

        heat_nos = extract_heatnos_from_history(hist_html)
        heat_date_map = map_heat_dates_from_history(hist_html)
        print(f"[info] {driver_name}: found {len(heat_nos)} heats on history page")

        for idx, heat in enumerate(heat_nos, 1):
            time.sleep(0.5)

            # EARLY year filter using history date (keeps logs clean and saves fetches)
            hist_dt = heat_date_map.get(heat)
            if hist_dt and hist_dt.year < START_YEAR:
                if DEBUG:
                    print(f"[debug] heat {heat}: {hist_dt.date()} < {START_YEAR}; skip (from history)")
                continue

            variants = [
                (HEAT_DETAILS_URL.format(heat=heat), "default"),
                (HEAT_DETAILS_URL_SHOW.format(heat=heat), "show"),
                (HEAT_DETAILS_PRINT_URL.format(heat=heat), "print"),
            ]
            best = {"variant": None, "html": None, "racer_laps": {}, "keys": -1}

            for url, tag in variants:
                try:
                    html = fetch(session, url)
                except Exception as e:
                    if DEBUG:
                        print(f"[debug] heat {heat}: fetch failed for '{tag}': {e}")
                    continue

                # dump debug HTML (capped per driver)
                dump_debug_html(heat, tag, html, driver_id, debug_counter)

                # parse now
                laps_by_racer = parse_laps_by_racer_any(html)
                num_keys = len(laps_by_racer)
                if DEBUG:
                    print(f"[debug] heat {heat}: variant '{tag}' produced {num_keys} racer sections")
                if num_keys > best["keys"]:
                    best = {"variant": tag, "html": html, "racer_laps": laps_by_racer, "keys": num_keys}

            if not best["html"] or best["keys"] <= 0:
                if DEBUG:
                    print(f"[debug] heat {heat}: no variant returned usable HTML")
                continue

            if DEBUG:
                print(f"[debug] heat {heat}: using variant '{best['variant']}' with {best['keys']} racer sections")

            # Determine the date to write (prefer page, fallback to history)
            page_dt = heat_datetime_from_html(best["html"])
            heat_dt = page_dt or hist_dt
            if heat_dt and heat_dt.year < START_YEAR:
                if DEBUG:
                    print(f"[debug] heat {heat}: {heat_dt.date()} < {START_YEAR}; skip")
                continue

            # map CustID -> display name for this heat
            id_to_name = map_custid_to_name_in_heat(best["html"])
            disp_name = id_to_name.get(driver_id, driver_name)

            # pick laps for this driver
            racer_laps = best["racer_laps"]
            laps = None
            if disp_name in racer_laps:
                laps = racer_laps[disp_name]
            if laps is None:
                disp_norm = norm(disp_name)
                for k in list(racer_laps.keys()):
                    if norm(k) == disp_norm:
                        laps = racer_laps[k]; break
            if laps is None:
                for k in list(racer_laps.keys()):
                    if norm(k).startswith(norm(disp_name)) or norm(disp_name).startswith(norm(k)):
                        laps = racer_laps[k]; break
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

            iso = heat_dt.replace(microsecond=0).isoformat() if heat_dt else ""
            with open(OUT_CSV, "a", newline="", encoding="utf-8") as fa:
                wa = csv.writer(fa)
                for lap_num, lap_sec in laps:
                    wa.writerow([disp_name, driver_id, heat, iso, lap_num, lap_sec])

            if idx % 10 == 0:
                print(f"[info] {driver_name}: processed {idx}/{len(heat_nos)} heats")

    print(f"[info] Wrote {OUT_CSV}")

if __name__ == "__main__":
    main()
