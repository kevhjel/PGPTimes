from __future__ import annotations
import json
import os
from typing import Dict, List, Any
from . import config

def ensure_dirs():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.HEATS_DIR, exist_ok=True)

def read_last_heat() -> int | None:
    if not os.path.exists(config.LAST_HEAT_FILE):
        return None
    with open(config.LAST_HEAT_FILE, "r", encoding="utf-8") as f:
        s = f.read().strip()
        if s.isdigit():
            return int(s)
    return None

def write_last_heat(heat_no: int):
    with open(config.LAST_HEAT_FILE, "w", encoding="utf-8") as f:
        f.write(str(heat_no))

def heat_path(heat_no: int) -> str:
    return f"{config.HEATS_DIR}/{heat_no}.json"

def write_heat(heat_no: int, payload: Dict[str, Any]):
    with open(heat_path(heat_no), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

def list_heat_files() -> List[int]:
    if not os.path.isdir(config.HEATS_DIR):
        return []
    heats = []
    for name in os.listdir(config.HEATS_DIR):
        if name.endswith(".json") and name[:-5].isdigit():
            heats.append(int(name[:-5]))
    return sorted(heats)

def write_json(path: str, obj: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def read_watchlist() -> List[str]:
    if not os.path.exists(config.WATCHLIST_FILE):
        return []
    try:
        with open(config.WATCHLIST_FILE, "r", encoding="utf-8") as f:
            names = json.load(f)
        return [str(x).strip() for x in names if str(x).strip()]
    except Exception:
        return []
