import json, os, re

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")
HEATS_DIR = os.path.join(DATA_DIR, "heats")
LAST_HEAT = os.path.join(DATA_DIR, "last_heat.txt")

def is_empty_heat(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        drivers = obj.get("drivers", [])
        # consider empty if drivers missing/empty
        return not drivers
    except Exception:
        # malformed json counts as empty/bad
        return True

def main():
    if not os.path.isdir(HEATS_DIR):
        print("No heats dir:", HEATS_DIR)
        return
    removed = 0
    kept_heat_nos = []
    for name in os.listdir(HEATS_DIR):
        if not name.endswith(".json"):
            continue
        path = os.path.join(HEATS_DIR, name)
        if is_empty_heat(path):
            os.remove(path)
            removed += 1
        else:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    obj = json.load(f)
                hn = int(obj.get("heat_no") or re.sub(r"\D", "", os.path.splitext(name)[0]) or 0)
                if hn:
                    kept_heat_nos.append(hn)
            except Exception:
                # malformed → already removed or skip
                pass

    # Recompute last_heat.txt as the max kept heat number (if any)
    if kept_heat_nos:
        new_last = max(kept_heat_nos)
        with open(LAST_HEAT, "w", encoding="utf-8") as f:
            f.write(str(new_last))
        print(f"Removed {removed} bad heats. New last_heat: {new_last}")
    else:
        # no good heats left; remove last_heat.txt
        if os.path.exists(LAST_HEAT):
            os.remove(LAST_HEAT)
        print(f"Removed {removed} bad heats. No valid heats remain; last_heat.txt cleared.")

if __name__ == "__main__":
    main()
