from __future__ import annotations

# ClubSpeed site to target
SITE_BASE_URL = "https://pgpkent.clubspeedtiming.com"

# Where the HeatDetails pages live relative to base
HEAT_DETAILS_PATH = "/sp_center/HeatDetails.aspx"

# Optional: Lap Times pop-up page name fragment; we’ll discover links dynamically, but this helps recognition
LAP_TIMES_HINT = "LapTimes"

# Starting heat number for backfill
START_HEAT_NO = 75533

# Politeness
REQUEST_TIMEOUT_SEC = 20
REQUEST_RETRY = 3
REQUEST_SLEEP_BETWEEN_SEC = 1.5

# Stop conditions:
# - how many consecutive missing heats (404 / empty page) before we assume we hit the end
MAX_CONSECUTIVE_MISSES = 30

# If you want to exclude heat types (e.g., Endurance Race), put display strings here
EXCLUDE_HEAT_TYPES = []   # e.g., ["Endurance Race"]

# File system layout
DATA_DIR = "data"
HEATS_DIR = f"{DATA_DIR}/heats"
LAST_HEAT_FILE = f"{DATA_DIR}/last_heat.txt"
DRIVER_INDEX_FILE = f"{DATA_DIR}/driver_index.json"
SUMMARY_FILE = f"{DATA_DIR}/summary.json"
WATCHLIST_FILE = f"{DATA_DIR}/drivers_watchlist.json"

# User-Agent for requests (helps avoid generic blocks)
USER_AGENT = "PGPTimes-HeatScraper/1.0 (+github.com/kevhjel/PGPTimes)"
