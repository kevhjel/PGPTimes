from __future__ import annotations
from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Tuple
import re
from dateutil import parser as dtp

# Utility to extract simple label/value from common HeatDetails layouts
def _get_text(el) -> str:
    if not el:
        return ""
    return " ".join(el.get_text(separator=" ", strip=True).split())

def _maybe_parse_datetime(text: str) -> Optional[str]:
    # ClubSpeed often includes date/time on the page near headings
    try:
        dt = dtp.parse(text, fuzzy=True)
        return dt.isoformat()
    except Exception:
        return None

def parse_heat_details_html(html: str) -> Dict:
    """
    Parse a HeatDetails.aspx page. This aims to be resilient across minor markup changes by:
     - finding "Heat #" / "Heat No" text patterns
     - extracting "Heat Type" from labels (e.g., id='lblRaceType' or text 'Race Type')
     - discovering a driver results table by headers like 'Driver', 'Pos', 'Kart'
     - collecting 'Lap Times' links per driver if present (href containing 'LapTimes')

    Returns a dict:
    {
      "heat_no": 82271,
      "heat_type": "Arrive & Drive",
      "start_time_iso": "...",  # if discoverable
      "drivers": [
        {
          "name": "Jane Racer",
          "position": 1,
          "kart": "12",
          "best_lap_seconds": 81.234,  # if table provides it; optional
          "lap_times_url": "https://...LapTimes...CustID=...",
          "laps": [81.234, 82.100, ...],                # only present if we fetch per-driver page
          "lap_positions": [1,2,2,...]                  # optional if present on lap popup
        },
        ...
      ]
    }
    """
    soup = BeautifulSoup(html, "lxml")

    # ---- heat number ----------
    heat_no = None
    # try in title or header text
    title_text = _get_text(soup.find("title"))
    m = re.search(r"(?:Heat\s*#?\s*|HeatNo\s*[:=]\s*)(\d+)", title_text, re.I)
    if not m:
        # try h1/h2
        for hx in soup.find_all(["h1", "h2", "h3", "span", "div"]):
            t = _get_text(hx)
            mm = re.search(r"(?:Heat\s*#?\s*|HeatNo\s*[:=]\s*)(\d+)", t, re.I)
            if mm:
                m = mm
                break
    if m:
        heat_no = int(m.group(1))

    # ---- heat type ------------
    heat_type = ""
    # common id on ClubSpeed: lblRaceType
    race_type_node = soup.find(id=re.compile(r"lblRaceType", re.I))
    if race_type_node:
        heat_type = _get_text(race_type_node)
    else:
        # fallback: look for "Race Type" or "Heat Type" labels near spans
        for label in soup.find_all(["td", "span", "div", "th"]):
            t = _get_text(label)
            if re.search(r"(heat|race)\s*type", t, re.I):
                # next sibling or nearby span
                nxt = label.find_next(["td", "span", "div"])
                if nxt:
                    heat_type = _get_text(nxt)
                    break

    # ---- start time (best-effort) ----
    start_time_iso = None
    # Sometimes a 'Start Time' label exists
    for label in soup.find_all(["td", "span", "div", "th"]):
        t = _get_text(label)
        if re.search(r"(start\s*time|date\s*time|session\s*time)", t, re.I):
            cand = _get_text(label.find_next(["td", "span", "div"]))
            iso = _maybe_parse_datetime(cand)
            if iso:
                start_time_iso = iso
                break
    if not start_time_iso:
        # try to parse any date-ish phrase in large headers
        for hx in soup.find_all(["h1","h2","h3","div","span"]):
            iso = _maybe_parse_datetime(_get_text(hx))
            if iso:
                start_time_iso = iso
                break

    # ---- drivers table ----------
    drivers: List[Dict] = []
    # find candidate tables that have headers like Driver, Pos, Kart, Best Lap, Laps
    candidates = []
    for table in soup.find_all("table"):
        header_cells = table.find_all(["th"])
        header_texts = [ _get_text(th) for th in header_cells ]
        joined = " | ".join(header_texts).lower()
        if any(k in joined for k in ["driver", "racer", "pos", "kart", "best", "laps"]):
            candidates.append(table)

    def parse_float_time(cell_text: str) -> Optional[float]:
        # times come like "1:21.234" or "81.234"
        s = cell_text.strip()
        if not s:
            return None
        try:
            if ":" in s:
                m, ss = s.split(":", 1)
                return int(m)*60 + float(ss)
            return float(s)
        except Exception:
            return None

    best_table = candidates[0] if candidates else None
    if best_table:
        # build column index
        header_cells = best_table.find_all("th")
        headers = [ _get_text(th).lower() for th in header_cells ]
        rows = best_table.find_all("tr")[1:]  # skip header
        for tr in rows:
            cells = tr.find_all(["td","th"])
            if len(cells) < 2:
                continue
            cell_texts = [ _get_text(td) for td in cells ]

            def col(name: str) -> Optional[int]:
                for i,h in enumerate(headers):
                    if name in h:
                        return i
                return None

            pos_i = col("pos")
            name_i = col("driver") if col("driver") is not None else col("racer")
            kart_i = col("kart")
            best_i = col("best")

            name = cell_texts[name_i] if name_i is not None and name_i < len(cell_texts) else ""
            position = int(re.sub(r"[^\d]", "", cell_texts[pos_i])) if pos_i is not None and re.search(r"\d", cell_texts[pos_i]) else None
            kart = re.sub(r"[^\dA-Za-z-]+", "", cell_texts[kart_i]) if kart_i is not None and kart_i < len(cell_texts) else None
            best_lap_seconds = parse_float_time(cell_texts[best_i]) if best_i is not None and best_i < len(cell_texts) else None

            # try to find a "Lap Times" link in this row
            lap_link = None
            for a in tr.find_all("a", href=True):
                if re.search(r"LapTimes", a["href"], re.I):
                    lap_link = a["href"]
                    break

            drivers.append({
                "name": name,
                "position": position,
                "kart": kart,
                "best_lap_seconds": best_lap_seconds,
                "lap_times_url": lap_link,
                "laps": None,
                "lap_positions": None,
            })

    return {
        "heat_no": heat_no,
        "heat_type": heat_type,
        "start_time_iso": start_time_iso,
        "drivers": drivers,
    }

def parse_laptimes_popup(html: str) -> Tuple[List[float], Optional[List[int]]]:
    """
    Parse a 'LapTimes...' popup/page if present. We look for a table with headers like 'Lap', 'Time', 'Pos'.
    Returns (times_seconds, positions_or_None)
    """
    soup = BeautifulSoup(html, "lxml")
    times: List[float] = []
    positions: List[int] = []
    table = None
    for t in soup.find_all("table"):
        head = " | ".join(_get_text(th).lower() for th in t.find_all("th"))
        if any(k in head for k in ["lap", "time"]) and ("pos" in head or "position" in head):
            table = t
            break
    if not table:
        # fallback: find any table with a 'Lap' header
        for t in soup.find_all("table"):
            head = " | ".join(_get_text(th).lower() for th in t.find_all("th"))
            if "lap" in head:
                table = t
                break
    if table:
        rows = table.find_all("tr")[1:]
        for tr in rows:
            tds = tr.find_all("td")
            cells = [_get_text(td) for td in tds]
            if not cells:
                continue

            # coarsely detect columns
            # assume lap num in first, time in second, pos maybe 3rd
            def parse_time(s: str) -> Optional[float]:
                s = s.strip()
                if not s or not re.search(r"[\d.]", s):
                    return None
                try:
                    if ":" in s:
                        m, ss = s.split(":", 1)
                        return int(m)*60 + float(ss)
                    return float(s)
                except Exception:
                    return None

            # try to find time cell by pattern
            time_val = None
            pos_val = None
            for c in cells:
                tt = parse_time(c)
                if tt is not None:
                    time_val = tt
                    break
            # position: first int-ish different from lap number
            for c in cells:
                if re.fullmatch(r"\d+", c):
                    pos_val = int(c)
                    # don't overthink; keep first
                    break
            if time_val is not None:
                times.append(time_val)
                positions.append(pos_val if pos_val is not None else -1)

    return times, (positions if positions else None)
