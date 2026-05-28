# Halal Stock Checker (AAOIFI, SEC-backed)

An iRizq.com tool for screening US stocks against AAOIFI Islamic finance standards.
Frontend UI and screening logic are unchanged; financial data now comes from a local SEC-backed Postgres cache.

## Live App

[Link to be added after deployment]

## Features

- Business sector screening (prohibits banking, alcohol, gambling, etc.)
- Financial ratio screening (debt, cash, non-halal income)
- AAOIFI-standard thresholds (unchanged)
- SEC EDGAR + SEC XBRL Company Facts ingestion
- PostgreSQL cache for normalized facts and final screening results
- Weekly refresh scheduler + manual admin refresh endpoint
- Frontend requests served from local DB (no live SEC calls in user request path)

## How to Run Locally

```bash
git clone [your-repo-url]
cd halal-stock-checker
pip install -r requirements.txt
python init_db.py
# optional: pre-load a ticker
python run_weekly_refresh.py --ticker AAPL
streamlit run app.py
```

## Environment Variables

```bash
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/halal_stocks
SEC_USER_AGENT="HalalStockChecker your@email.com"
SEC_TIMEOUT_SECONDS=20
SEC_RATE_LIMIT_PER_SECOND=5
SEC_MAX_RETRIES=4
REFRESH_CRON_DAY_OF_WEEK=sun
REFRESH_CRON_HOUR_UTC=3
REFRESH_CRON_MINUTE_UTC=0
REFRESH_MAX_FILINGS_PER_COMPANY=8
ADMIN_API_TOKEN=your-admin-token
LOG_LEVEL=INFO
```

## New Data Architecture

```
SEC filings index
  -> latest 10-Q / 10-K
  -> SEC company facts
  -> normalize tags + TTM calculations
  -> PostgreSQL (raw + normalized + halal result tables)
  -> Streamlit UI / API reads cached results
```

### Core tables

- `companies`
- `filings`
- `raw_financial_facts`
- `normalized_financials`
- `halal_screen_results`

Migration SQL: `migrations/001_sec_financial_pipeline.sql`

## How to Deploy to Streamlit Cloud

1. Push this project to a GitHub repository (make sure static/ folder with logo.png and icon.png is included)
2. Go to https://share.streamlit.io
3. Sign in with GitHub
4. Click "New app"
5. Select your GitHub repo, branch: main, main file: app.py
6. Click Deploy (takes ~2 minutes)
7. Copy the public URL and share with test users

## Adding Your Logo

1. Copy your logo to: static/logo.png (use transparent PNG background)
2. Resize a square version to 180x180px → save as: static/icon.png
3. Commit both files to GitHub and redeploy

## iPhone Home Screen Instructions (share with test users)

1. Open the app URL in Safari on iPhone
2. Tap the Share button (box with arrow at bottom of screen)
3. Scroll down and tap "Add to Home Screen"
4. Tap "Add" — the iRizq Halal Stocks icon appears on your home screen
5. Open it — it runs like a native app, full screen, no browser bar

## Screening Methodology

Based on AAOIFI Shariah Standards:

- Prohibited sectors: Banking, Insurance, Gambling, Alcohol, Tobacco, Adult Entertainment, Defense/Weapons
- Debt / Market Cap must be under 33%
- Cash / Market Cap must be under 33%
- Non-permissible income / Revenue must be under 5%
- Ratios within 5% of threshold = Questionable

## Disclaimer

This tool is for educational purposes only and does not constitute a fatwa or financial advice. Always consult a qualified Islamic finance scholar for personal guidance.

## Tech Stack

- Python 3.10+
- Streamlit
- FastAPI (admin + cached screen API)
- PostgreSQL + SQLAlchemy
- APScheduler
- SEC EDGAR APIs + SEC XBRL Company Facts
- Deployed on Streamlit Cloud (free tier)
- Branded for iRizq.com