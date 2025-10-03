from __future__ import annotations
from bs4 import BeautifulSoup
from typing import Dict, List, Optional, Tuple
import re
from dateutil import parser as dtp

# ------------------------------
# helpers
# ------------------------------

def _get_text(el) -> str:
    if not el:
        return ""
    return " ".join(el.get_text(separator=" ", strip=True).split())

def _maybe_parse_datetime(text: str) -> Optional[str]:
    if not text:
        return None
    try:
        # US-style dates like 8/23/2025 1:15 PM parse fine with dateutil
        dt = dtp.parse(text, fuzzy=True, dayfirst=False)
        return dt.isoformat()
    except Exception:
        return None

def _parse_time_to_seconds(s: str) -> Optional[float]:
    s = (s or "").strip()
    if not s or not re.search(r"[\d.]", s):
        return None
    try:
        if ":" in s:
            m, ss = s.split(":", 1)
            return int(m) * 60 + float(ss)
        return float(s)
    except Exception:
        return None

# ------------------------------
# main page parser
# ------------------------------

def parse_heat_details_html(html: str) -> Dict:
    """
    Parse a HeatDetails.aspx page, prioritizing:
      - driver/laps from LapTimesContainer
      - start time from exact #lblDate

    Returns:
    {
      "heat_no": int,
      "heat_type": str,
      "start_time_iso": str|None,
      "drivers": [...]
    }
    """
    soup = BeautifulSoup(html, "lxml")

    # ---- heat number ----------
    heat_no = None
    title_text = _get_text(soup.find("title"))
    m = re.search(r"(?:Heat\s*#?\s*|HeatNo\s*[:=]\s*)(\d+)", title_text, re.I)
    if not m:
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
    race_type_node = soup.find(id=re.compile(r"lblRaceType", re.I))
    if race_type_node:
        heat_type = _get_text(race_type_node)
    else:
        for label in soup.find_all(["td", "span", "div", "th"]):
            t = _get_text(label)
            if re.search(r"(heat|race)\s*type", t, re.I):
                nxt = label.find_next(["td", "span", "div"])
                if nxt:
                    heat_type = _get_text(nxt)
                    break

    # ---- start date/time (STRICT: from #lblDate) ----
    start_time_iso = None

    # 1) Exact id match first
    date_exact = soup.find(id="lblDate")
    if date_exact:
        start_time_iso = _maybe_parse_datetime(_get_text(date_exact))

    # 2) If still missing, look for a table row where left cell contains #lblDate1 ("Date")
    #    and the right sibling cell (HeatResultsRightCell) holds the value.
    if not start_time_iso:
        for tr in soup.find_all("tr"):
            left = tr.find("td", class_=re.compile(r"\bHeatResultsLeftCell\b", re.I))
            right = tr.find("td", class_=re.compile(r"\bHeatResultsRightCell\b", re.I))
            if not left or not right:
                continue
            left_lbl = left.find(id="lblDate1")
            if left_lbl and _get_text(left_lbl).lower() == "date":
                # prefer a span inside the right cell (often #lblDate)
                span = right.find("span")
                txt = _get_text(span) if span else _get_text(right)
                start_time_iso = _maybe_parse_datetime(txt)
                if start_time_iso:
                    break

    # 3) LAST resort (avoid pulling the wrong thing): any obvious date-ish label/value nearby
    if not start_time_iso:
        for label in soup.find_all(["td", "span", "div", "th"]):
            t = _get_text(label)
            if re.search(r"(start\s*time|date\s*time|session\s*time)", t, re.I):
                cand = _get_text(label.find_next(["td", "span", "div"]))
                iso = _maybe_parse_datetime(cand)
                if iso:
                    start_time_iso = iso
                    break

    # ------------------------------
    # Preferred path: LapTimesContainer
    # ------------------------------
    drivers: List[Dict] = []
    container = soup.find("table", class_=re.compile(r"\bLapTimesContainer\b", re.I))
    if container:
        inner = container.find_all("table", class_=re.compile(r"\bLapTimes\b", re.I))
        for dtbl in inner:
            # Driver name in <th colspan="2">Name</th>
            th = dtbl.find("th")
            name = _get_text(th)

            laps: List[float] = []
            lap_positions: List[int] = []
            # rows with lap data are class LapTimesRow / LapTimesRowAlt
            for tr in dtbl.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) < 2:
                    continue
                lap_idx_txt = _get_text(tds[0])
                val = _get_text(tds[1]).replace("\xa0", " ")
                # only rows with an integer lap number
                if not re.fullmatch(r"\d+", lap_idx_txt):
                    continue

                # extract position inside brackets "[3]"
                mpos = re.search(r"\[(\d+)\]", val)
                pos_val = int(mpos.group(1)) if mpos else None

                # strip bracketed suffix to get pure time
                time_txt = re.sub(r"\[[^\]]+\]", "", val).strip()
                tsec = _parse_time_to_seconds(time_txt)
                if tsec is None:
                    # empty "&nbsp;" or invalid cell
                    continue

                laps.append(tsec)
                lap_positions.append(pos_val if pos_val is not None else -1)

            best = min(laps) if laps else None
            # infer "finish position" as the last non-empty lap position
            finish_pos = None
            for p in reversed(lap_positions):
                if isinstance(p, int) and p > 0:
                    finish_pos = p
                    break

            drivers.append({
                "name": name,
                "position": finish_pos,
                "kart": None,                     # not present in this container
                "best_lap_seconds": best,
                "lap_times_url": None,            # no per-driver link needed
                "laps": laps if laps else None,
                "lap_positions": lap_positions if lap_positions else None,
            })

        return {
            "heat_no": heat_no,
            "heat_type": heat_type,
            "start_time_iso": start_time_iso,
            "drivers": drivers,
        }

    # ------------------------------
    # Generic fallback (only if container missing)
    # ------------------------------
    candidates = []
    for table in soup.find_all("table"):
        header_cells = table.find_all(["th"])
        header_texts = [_get_text(th) for th in header_cells]
        joined = " | ".join(h.lower() for h in header_texts)
        if any(k in joined for k in ["driver", "racer", "pos", "kart", "best", "laps"]):
            candidates.append(table)

    def parse_float_time(cell_text: str) -> Optional[float]:
        return _parse_time_to_seconds(cell_text)

    if candidates:
        best_table = candidates[0]
        header_cells = best_table.find_all("th")
        headers = [_get_text(th).lower() for th in header_cells]
        rows = best_table.find_all("tr")[1:]
        for tr in rows:
            cells = tr.find_all(["td","th"])
            if len(cells) < 2:
                continue
            cell_texts = [_get_text(td) for td in cells]

            def col(name: str) -> Optional[int]:
                for i, h in enumerate(headers):
                    if name in h:
                        return i
                return None

            pos_i  = col("pos")
            name_i = col("driver") if col("driver") is not None else col("racer")
            kart_i = col("kart")
            best_i = col("best")

            name = cell_texts[name_i] if name_i is not None and name_i < len(cell_texts) else ""
            position = int(re.sub(r"[^\d]", "", cell_texts[pos_i])) if pos_i is not None and re.search(r"\d", cell_texts[pos_i]) else None
            kart = re.sub(r"[^\dA-Za-z-]+", "", cell_texts[kart_i]) if kart_i is not None and kart_i < len(cell_texts) else None
            best_lap_seconds = parse_float_time(cell_texts[best_i]) if best_i is not None and best_i < len(cell_texts) else None

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

# ------------------------------
# per-driver popup parser (compatibility)
# ------------------------------

def parse_laptimes_popup(html: str) -> Tuple[List[float], Optional[List[int]]]:
    soup = BeautifulSoup(html, "lxml")
    times: List[float] = []
    positions: List[int] = []
    table = None
    for t in soup.find_all("table"):
        head = " | ".join(_get_text(th).lower() for th in t.find_all("th"))
        if ("lap" in head and "time" in head) or ("lap" in head and "position" in head) or ("laps" in head):
            table = t
            break
    if not table:
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
            time_val = None
            for c in cells:
                tt = _parse_time_to_seconds(c)
                if tt is not None:
                    time_val = tt
                    break
            pos_val = None
            for c in cells:
                if re.fullmatch(r"\d+", c):
                    pos_val = int(c)
                    break
            if time_val is not None:
                times.append(time_val)
                positions.append(pos_val if pos_val is not None else -1)
    return times, (positions if positions else None)
