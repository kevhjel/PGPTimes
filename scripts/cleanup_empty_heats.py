# scraper/cleanup_empty_heats.py
"""
Deletes any heat JSON files that do not contain driver data.

Usage:
    python -m scraper.cleanup_empty_heats
"""

import os
import json

def is_empty_heat(data):
    """Return True if a parsed heat JSON is missing or has empty driver data."""
    if not isinstance(data, dict):
        return True
    drivers = data.get("drivers", [])
    if not isinstance(drivers, list):
        return True
    return len(drivers) == 0

def main():
    heats_dir = os.path.join("data", "heats")
    if not os.path.exists(heats_dir):
        print("No data/heats directory found.")
        return

    files = [f for f in os.listdir(heats_dir) if f.endswith(".json")]
    deleted = 0

    for f in sorted(files):
        path = os.path.join(heats_dir, f)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            print(f"⚠️ Error reading {f}: {e}")
            os.remove(path)
            print(f"🗑️ Deleted corrupt file {f}")
            deleted += 1
            continue

        if is_empty_heat(data):
            os.remove(path)
            print(f"🗑️ Deleted empty heat {f}")
            deleted += 1

    print(f"\n✅ Cleanup complete. Deleted {deleted} empty or corrupt files.")

if __name__ == "__main__":
    main()
