# PGP Heats — Full Backfill Scraper

Scrapes **every heat** from PGP Kent’s ClubSpeed pages, starting at a configurable `START_HEAT_NO` (default **75533**), and stores per-heat JSON with:
- Heat metadata (type, start time, source URL)
- All drivers in the heat (name, position, kart, best lap)
- Each driver’s full lap list when available (follows the “Lap Times” link on the row)

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m scraper.run            # continues from data/last_heat.txt or starts at 75533
# or bounded runs:
python -m scraper.run 80000 80500
