# scraper/build_endurance_index.py
"""
Scan data/heats/*.json and write data/endurance_index.json
Schema:
{
  "last_updated_utc": "...Z",
  "count": <int>,
  "rows": [
    {"heat_no": 82787, "start_time_iso": "2025-08-23T13:15:00", "first": "A", "second": "B", "third": "C"},
    ...
  ]
}
"""

import os, json, time

DATA_DIR = "data"
HEATS_DIR = os.path.join(DATA_DIR, "heats")
OUT_PATH = os.path.join(DATA_DIR, "endurance_index.json")

def is_endurance(heat_type: str) -> bool:
    return isinstance(heat_type, str) and ("endurance" in heat_type.lower())

def podium_from_drivers(drivers):
    # sort by numeric position ascending
    arr = [d for d in (drivers or []) if isinstance(d.get("position"), (int, float))]
    arr.sort(key=lambda d: d["position"])
    first = (arr[0]["name"] if len(arr) > 0 else "") or ""
    second = (arr[1]["name"] if len(arr) > 1 else "") or ""
    third = (arr[2]["name"] if len(arr) > 2 else "") or ""
    return first, second, third

def main():
    rows = []
    if not os.path.isdir(HEATS_DIR):
        os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump({"last_updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "count": 0, "rows": []}, f, indent=2)
        return

    for root, _, files in os.walk(HEATS_DIR):
        for fn in files:
            if not fn.endswith(".json"): continue
            p = os.path.join(root, fn)
            try:
                obj = json.load(open(p, "r", encoding="utf-8"))
            except Exception:
                continue
            drivers = obj.get("drivers") or []
            if not drivers:  # skip empty heats
                continue
            heat_type = obj.get("heat_type") or ""
            if not is_endurance(heat_type):
                continue
            heat_no = obj.get("heat_no")
            first, second, third = podium_from_drivers(drivers)
            rows.append({
                "heat_no": heat_no,
                "start_time_iso": obj.get("start_time_iso") or "",
                "first": first,
                "second": second,
                "third": third,
            })

    # sort: newest first by time, fallback to heat_no
    rows.sort(key=lambda r: ((r.get("start_time_iso") or ""), r.get("heat_no") or 0), reverse=True)

    out = {
        "last_updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(rows),
        "rows": rows,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
