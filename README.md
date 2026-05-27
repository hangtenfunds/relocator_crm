# Relocation CRM Scrapers

Automated intel pipeline that feeds the CRM Inbox with new corporate
relocation signals. Phase 2 ships with the **OEDIT scraper**, which
pulls Colorado Economic Development Commission approved projects each
month and posts them to the Inbox for review.

Future scrapers (Bisnow Denver, BusinessDen, Mile High CRE, etc.) will
plug into the same `sheets_client` and infrastructure.

---

## What's in here

```
relocation_scrapers/
├── main.py                  CLI entry point
├── oedit_scraper.py         OEDIT-specific fetch + parse logic
├── sheets_client.py         Reusable Google Sheets read/write wrapper
├── config.py                Loads credentials + spreadsheet ID from env
├── test_parser.py           Parser test (synthetic HTML, no network)
├── requirements.txt         Python dependencies
├── .env.example             Template for local env vars
├── .gitignore               Keeps secrets out of git
└── .github/workflows/
    └── scrape.yml           GitHub Actions schedule (third Friday monthly)
```

---

## Setup — what you need to do (≈30 minutes, one time)

### Step 1 — Create a Google Cloud service account (15 min)

A service account is a robot identity that can read/write your Sheet
without anyone being logged in. It's the standard way to give a script
access.

1. Go to **https://console.cloud.google.com/**
2. **Create a new project** (top-left dropdown → New Project). Name it
   "Relocation CRM" or similar. Region doesn't matter.
3. Once the project is selected, in the search bar at the top, type
   **"Google Sheets API"**. Click the result → **Enable**.
4. In the sidebar, go to **APIs & Services → Credentials**.
5. Click **+ Create Credentials → Service account**.
   - Service account name: `relocation-crm-scraper`
   - Click **Create and Continue**
   - Skip the optional role assignment (Continue)
   - Skip the optional user access (Done)
6. You'll see the service account in the list. Click its email
   (looks like `relocation-crm-scraper@…iam.gserviceaccount.com`).
   **Copy this email address** — you'll need it in the next step.
7. Go to the **Keys** tab → **Add Key → Create new key → JSON**.
   A JSON file downloads to your computer.
   **Rename it to `service-account.json`** and keep it safe — this is
   effectively the password for the robot.

### Step 2 — Share the Sheet with the service account (1 min)

1. Open your Relocation CRM Google Sheet.
2. Click **Share** (top-right).
3. Paste the service account email from Step 1.6.
4. Give it **Editor** access.
5. **Uncheck "Notify people"** (it can't receive email anyway).
6. Click **Share**.

The robot can now write to your Sheet.

### Step 3 — Local setup to test it (5 min)

You can run the scraper from your own machine first to confirm it works,
then move to GitHub Actions for automation.

1. **Install Python 3.10+** if you don't have it
   ([python.org/downloads](https://python.org/downloads)).
2. Open a terminal and navigate to the `relocation_scrapers/` folder.
3. Create a virtual environment (recommended, not required):
   ```
   python3 -m venv .venv
   source .venv/bin/activate          # macOS/Linux
   .venv\Scripts\activate             # Windows
   ```
4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
5. Copy the env template:
   ```
   cp .env.example .env
   ```
6. Edit `.env` and fill in:
   - `SPREADSHEET_ID` — the long string from your Sheet's URL between
     `/d/` and `/edit`.
   - `GOOGLE_APPLICATION_CREDENTIALS` — path to `service-account.json`
     (e.g., `./service-account.json` if it's in the same folder).
7. **Move `service-account.json` into the `relocation_scrapers/` folder**
   (or set the env var to wherever you keep it).
8. Run a **dry run** to make sure parsing works (won't touch the Sheet):
   ```
   python main.py --dry-run -v
   ```
   You should see parsed projects from the last 3 months printed to
   the terminal.
9. If that looks right, do a **real run**:
   ```
   python main.py -v
   ```
   New rows will appear in your Inbox tab. Apps Script will auto-fill
   the `inbox_id` and `found_at` columns as soon as the rows land.

### Step 4 — Schedule it on GitHub Actions (10 min)

This is the "set and forget" part — automated monthly runs.

1. **Create a GitHub repo** (private is fine, free). Push this folder
   to it. The folder structure is already arranged the way GitHub
   Actions expects it.
2. In your repo, go to **Settings → Secrets and variables → Actions**.
3. Click **New repository secret** twice and add:
   - **`SPREADSHEET_ID`** — same value as in your `.env`.
   - **`GOOGLE_SHEETS_CREDENTIALS_JSON`** — paste the **full contents**
     of `service-account.json` as a single string (it's JSON; just
     copy-paste everything including the curly braces).
4. The workflow is already in `.github/workflows/scrape.yml`. It will
   run automatically every Friday between the 15th and 21st of the
   month (covering the day after each EDC meeting). The dedup logic
   means running multiple times is safe — duplicates are skipped.
5. **Test the schedule manually:** go to the **Actions** tab on GitHub,
   pick "OEDIT Scraper" from the left sidebar, click **Run workflow**,
   and choose `--dry-run` or a real run.

You should see logs like:
```
Fetching https://oedit.colorado.gov/news/april-2026-edc-…
  Parsed 4 projects from april 2026
Total projects parsed: 12
Loaded 8 existing companies for matching
Wrote 9 new rows to Inbox (dedup skipped 3)
```

---

## Day-to-day operation

Once Phase 2 is running:

1. The scraper runs each Friday in the second half of the month.
2. New OEDIT projects appear in your **Inbox** tab Monday morning at
   the latest.
3. The daily digest email (from Apps Script) tells you how many are
   pending review.
4. On Monday, during your weekly routine, you triage each Inbox row
   ("Create new" / "Link to existing" / "Ignore"). See `CRM_SOP.md`.
5. Apps Script handles the rest — creating the Companies record,
   linking the Signal, archiving the Inbox row.

---

## Running locally — common commands

```bash
# Standard run (last 3 months, write to Sheet)
python main.py

# Last 6 months (useful for the first run to backfill)
python main.py --months 6

# Specific month
python main.py --target 2026-04

# Dry run (parse and print only, no writes)
python main.py --dry-run -v

# Skip projects outside the Front Range
python main.py --front-range-only

# Run parser-only tests (no network, no credentials needed)
python test_parser.py
```

---

## Troubleshooting

### `gspread.exceptions.SpreadsheetNotFound`
The service account doesn't have access. Re-check Step 2 — make sure you
shared the Sheet with the service-account email and gave it Editor access.

### `ValueError: invalid literal for int() with base 10`
A regex caught something it shouldn't have. Re-run with `-v` and look at
which project triggered it; the parser is defensive but new page formats
can trip it up. Open an issue (or fix the regex) and re-run.

### Scraper returns 404 for the current month
The OEDIT page hasn't been posted yet (typically a few days to a week
after the meeting). The scraper handles this gracefully; just re-run
later. The default `--months 3` covers the lookback so you won't miss
anything.

### Two rows for the same project appeared
Shouldn't happen due to dedup, but if it does it usually means the
project name was slightly different between runs (e.g., a typo fix on
the OEDIT page). Mark one as "Ignore" in the Inbox to archive it.

### "Module not found: rapidfuzz"
You're missing a dependency. Run `pip install -r requirements.txt` again.

### GitHub Action fails with auth error
The `GOOGLE_SHEETS_CREDENTIALS_JSON` secret is malformed. Make sure you
pasted the **entire** JSON file content, including the outer `{` and `}`.
GitHub stores it as a single multiline string — that's fine.

---

## Adding more scrapers later

When we add Bisnow, BusinessDen, etc., the pattern is:

1. Create a new file `bisnow_scraper.py` with its own fetch/parse logic.
2. Have it return a list of dicts in the same shape as
   `OEDITProject.to_inbox_row()`.
3. Call it from `main.py` alongside the OEDIT scraper.
4. Add it to the GitHub Actions cron (probably daily for news feeds).

The dedup, fuzzy matching, and Sheets writing are all reusable.

---

## Maintenance

- **Quarterly:** spot-check a few OEDIT pages by eye against the parsed
  output. If OEDIT changes their page template, the parser may need
  updates.
- **Annually:** rotate the service account key in Google Cloud Console
  and update the secret in GitHub.
# relocator_crm
