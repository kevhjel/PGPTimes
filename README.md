# ClubSpeed Leaderboard (PGP Kent) — Starter Repo

This repo hosts a **static website (GitHub Pages)** that shows a leaderboard of people you've raced with, plus a **GitHub Actions** workflow that scrapes your heats **weekly** and updates the leaderboard data.

## What it does
- Scrapes your **RacerHistory** page (by your `CustID`) to collect recent HeatNos.
- For each heat, scrapes each racer's lap log and records their **best lap** and the **kart** used for that best lap.
- Aggregates across all heats and publishes **`data/leaderboard.json`**.
- The front‑end (`index.html` + `script.js`) renders a searchable/sortable table.
- Auto‑runs **weekly** via GitHub Actions and pushes updates.

> ⚠️ This starter is tailored for ClubSpeed pages like:  
> - `.../sp_center/RacerHistory.aspx?CustID=...`  
> - `.../sp_center/HeatDetails.aspx?HeatNo=...`

## Quick start

1. **Create a new GitHub repository** and upload all files from this starter.
2. In your repo, go to **Settings → Pages** and set:
   - **Build and deployment:** *Deploy from a branch*
   - **Branch:** `main` / `/ (root)`
   - Save — your site will appear at `https://<you>.github.io/<repo>/`
3. In **Settings → Secrets and variables → Actions → New repository secret**, add:
   - `CUST_ID` — your encoded Customer ID string (e.g. `MTExNDczMQ==`).
   - *(Optional)* `YEARS` — comma‑separated list like `2024,2025` (default is last 2 years).
   - *(Optional)* `SITE_BASE_URL` — if your ClubSpeed base differs, default is `https://pgpkent.clubspeedtiming.com`.
4. The workflow runs **weekly** (Monday 9:00 UTC). To run it now:
   - Go to **Actions → Scrape ClubSpeed leaderboard → Run workflow**.

## Local development

```bash
# Optional: run locally to test
python -m venv .venv && source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
export CUST_ID="YOUR_ID"  # or set in your shell
python scraper/scrape.py
# Open index.html in a browser (or use a simple HTTP server)
```

## Customize
- Change columns or formatting in **`index.html` / `script.js` / `style.css`**.
- Adjust scraping window in **`scraper/scrape.py`** (e.g. number of months to look back).
- Pin the list of heats by writing them to `data/heats.txt` (one HeatNo per line) — if present, the scraper will use that instead of discovering from RacerHistory.

## Data contract (data/leaderboard.json)
```jsonc
{
  "last_updated_utc": "2025-09-28T00:00:00Z",
  "source": "https://pgpkent.clubspeedtiming.com",
  "racers": [
    {
      "name": "Jane Racer",
      "best_lap_seconds": 81.234,
      "best_kart": "2",
      "best_heat_no": "82271",
      "best_lap_datetime": "2025-09-27T19:45:00Z"
    }
  ]
}
```

## Notes
- If ClubSpeed’s HTML changes, you may need to tweak CSS selectors in the scraper.
- Please respect the site’s usage; keep the weekly cadence (or slower).
- This project is for personal use and educational scraping only.
