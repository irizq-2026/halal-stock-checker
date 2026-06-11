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
FMP_API_KEY=your-fmp-api-key
FMP_BASE_URL=https://financialmodelingprep.com/api
FMP_TIMEOUT_SECONDS=15
REFRESH_CRON_DAY_OF_WEEK=sun
REFRESH_CRON_HOUR_UTC=3
REFRESH_CRON_MINUTE_UTC=0
REFRESH_MAX_FILINGS_PER_COMPANY=8
ADMIN_API_TOKEN=your-admin-token
ANALYTICS_ADMIN_PASSWORD=change-this-password
ANALYTICS_SESSION_SECRET=change-this-session-secret
ANALYTICS_COOKIE_NAME=uid
ANALYTICS_COOKIE_MAX_AGE_SECONDS=31536000
ANALYTICS_CACHE_TTL_SECONDS=30
ANALYTICS_SSLMODE=require
LOG_LEVEL=INFO
```

## Admin Analytics Setup (Render / Postgres)

This project now includes a lightweight internal analytics system backed by PostgreSQL.

### What it tracks

- `visit` events on `GET /` (page loads)
- `search` events on `GET /api/v1/screen/{ticker}` (stock checks)
- anonymous returning users via cookie (`uid` by default)
- traffic source from `utm_source` or `Referer` (fallback: `direct`)

### Database setup

- Uses the existing `DATABASE_URL` env var from Render
- Accepts Render-style URLs starting with `postgres://` (normalized automatically)
- Creates analytics table on API startup:
  - `events (id, event_type, user_id, ticker, source, timestamp)`

### Admin auth setup

Set these env vars in Render before using admin pages:

- `ANALYTICS_ADMIN_PASSWORD` (required; choose a strong password)
- `ANALYTICS_SESSION_SECRET` (required; long random secret)

### Admin routes

- `GET /admin-login` → login page
- `POST /admin-login` → session login
- `GET /admin` → analytics dashboard (protected)
- `GET /admin-logout` → logout

### Streamlit-native admin access

You can also open the admin dashboard directly inside the Streamlit app by adding a query parameter:

- `https://<your-streamlit-app>.streamlit.app/?page=admin`

For example:

- `https://test-halal-stock-checker.streamlit.app/?page=admin`

Use the same admin password from `ANALYTICS_ADMIN_PASSWORD`.

If login shows default-fallback warning, verify one of these is set and redeploy/restart:

- Streamlit Secrets: `ANALYTICS_ADMIN_PASSWORD = "your-password"`
- Environment variable: `ANALYTICS_ADMIN_PASSWORD=your-password`

### Dashboard metrics shown

- Total visits
- Total searches
- Unique users
- Return users (>1 event)
- Most searched tickers (top 10)
- Traffic source breakdown
- Conversion rate (`searches / visits`)
- Last 50 events

### Quick local verification

1. Start API service (for example: `uvicorn api:app --reload`).
2. Open:
   - `http://localhost:8000/?utm_source=reddit`
   - `http://localhost:8000/api/v1/screen/AAPL`
3. Login at `http://localhost:8000/admin-login`.
4. Confirm metrics update in `http://localhost:8000/admin`.

### Render notes

- `psycopg2-binary` is already in `requirements.txt`.
- Render free Postgres has connection/storage limits and expiration windows; plan upgrades for production workloads.
- Keep `/admin` private and do not share admin credentials.

## New Data Architecture

```
SEC filings index
  -> latest 10-Q / 10-K
  -> SEC company facts
  -> normalize tags + TTM calculations
  -> market cap fallback (FMP) when SEC market cap is unavailable/stale
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