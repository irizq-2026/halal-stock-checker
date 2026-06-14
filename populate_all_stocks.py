# ── HOW TO RUN ────────────────────────────────────────────────
#
# First time full population (all US stocks):
#   python populate_all_stocks.py
#
# Test run (first 20 tickers only — use this first):
#   python populate_all_stocks.py --test
#
# Dry run (log only, no DB writes):
#   python populate_all_stocks.py --dry-run
#
# Force run (bypass any run guards):
#   python populate_all_stocks.py --force
#
# Combine flags:
#   python populate_all_stocks.py --test --dry-run
#
# Required environment variables (.env or Render):
#   DATABASE_URL          = your PostgreSQL connection string
#   SEC_EDGAR_USER_AGENT  = "AppName admin@yourdomain.com"
#
# Estimated runtime for full US stock universe (~10,000 tickers):
#   SEC EDGAR:  ~6-8 hours (rate limited to 5 req/sec)
#   yfinance:   ~3-4 hours (batched)
#   Total:      ~10-12 hours (run overnight)
#
# ─────────────────────────────────────────────────────────────

import os
import sys
import time
import uuid
import csv
import re
import json
import requests
import psycopg2
import yfinance as yf
import pandas as pd
from pathlib import Path
from datetime import datetime
from psycopg2.extras import execute_values
from rapidfuzz import fuzz, process as fuzz_process
from dotenv import load_dotenv

load_dotenv()

# ── RUN MODE ──────────────────────────────────────────────────
FORCE_RUN = "--force" in sys.argv
DRY_RUN = "--dry-run" in sys.argv  # log only, no DB writes
TEST_MODE = "--test" in sys.argv  # run on first 20 tickers only
prefix = "[FORCE] " if FORCE_RUN else ""
dry_prefix = "[DRY RUN] " if DRY_RUN else ""
test_prefix = "[TEST] " if TEST_MODE else ""

# ── API RATE LIMITS ───────────────────────────────────────────
# SEC EDGAR: 5 requests/second max for sustained safe use
SEC_EDGAR_DELAY = 0.2  # 5 req/sec
SEC_RETRY_WAIT = 60  # wait 60s after 429
SEC_MAX_RETRIES = 3  # retries per request
SEC_BATCH_PAUSE = 30  # pause every 100 tickers
SEC_BATCH_PAUSE_COUNT = 100  # pause after this many tickers

# yfinance
YFINANCE_SINGLE_DELAY = 1.0  # between single fetches
YFINANCE_BATCH_DELAY = 3.0  # between batch downloads
YFINANCE_BATCH_SIZE = 50  # tickers per batch

# Ethical DB
ETHICAL_DB_DELAY = 5.0  # between ethical DB fetches
FUZZY_MATCH_THRESHOLD = 0.85  # min confidence for name match

# General
TICKER_DELAY = 2.0  # between processing each ticker
LOG_FILE = Path("population_log.txt")
DATA_DIR = Path(__file__).resolve().parent / "data"

# ── STATS TRACKER ─────────────────────────────────────────────
stats = {
    "total_tickers": 0,
    "sec_success": 0,
    "sec_failed": 0,
    "sec_skipped": 0,
    "yfinance_success": 0,
    "yfinance_failed": 0,
    "halal_missing": 0,
    "market_cap_missing": 0,
    "cik_missing": 0,
    "ethical_matches": {
        "bds": 0,
        "afsc": 0,
        "un_ohchr": 0,
        "who_profits": 0,
    },
    "failed_tickers": [],
    "skipped_tickers": [],
}

REQUIRED_ENV_VARS = [
    "DATABASE_URL",
    "SEC_EDGAR_USER_AGENT",
]


def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception as exc:
        print(f"[{timestamp}] [LOG ERROR] Could not write to {LOG_FILE}: {exc}")


def sec_get(url):
    headers = {
        "User-Agent": os.environ["SEC_EDGAR_USER_AGENT"],
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    }
    for attempt in range(1, SEC_MAX_RETRIES + 1):
        try:
            time.sleep(SEC_EDGAR_DELAY)
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                try:
                    return response.json()
                except Exception as exc:
                    log(f"  [ERROR] SEC JSON parse failed: {url} ({exc})")
                    return None
            elif response.status_code in [429, 403]:
                log(
                    f"  [RATE LIMIT] SEC attempt {attempt}/{SEC_MAX_RETRIES}. "
                    f"Waiting {SEC_RETRY_WAIT}s..."
                )
                time.sleep(SEC_RETRY_WAIT)
            elif response.status_code == 404:
                log(f"  [404] Not found: {url}")
                return None
            else:
                log(f"  [ERROR] SEC HTTP {response.status_code}: {url}")
                return None
        except requests.exceptions.Timeout:
            log(f"  [TIMEOUT] SEC request timed out: {url}")
            if attempt < SEC_MAX_RETRIES:
                time.sleep(SEC_RETRY_WAIT)
        except Exception as exc:
            log(f"  [EXCEPTION] SEC request failed (attempt {attempt}): {exc}")
            if attempt < SEC_MAX_RETRIES:
                time.sleep(SEC_RETRY_WAIT)
    log(f"  [FAILED] Max retries reached: {url}")
    return None


def yf_fetch_single(ticker):
    try:
        time.sleep(YFINANCE_SINGLE_DELAY)
        stock = yf.Ticker(ticker)
        info = stock.info
        if not info or len(info) < 5:
            log(f"  [EMPTY] yfinance returned no data for {ticker}")
            return None
        return info
    except Exception as exc:
        log(f"  [ERROR] yfinance single fetch failed for {ticker}: {exc}")
        return None


def yf_fetch_batch(tickers):
    try:
        time.sleep(YFINANCE_BATCH_DELAY)
        data = yf.download(
            tickers,
            period="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            timeout=60,
        )
        return data
    except Exception as exc:
        log(f"  [ERROR] yfinance batch failed: {exc}")
        return None


def db_upsert(conn, table, rows, conflict_col):
    if not rows or DRY_RUN:
        if DRY_RUN:
            log(f"  [DRY RUN] Would upsert {len(rows)} rows into {table}")
        return len(rows) if DRY_RUN else 0
    try:
        columns = list(rows[0].keys())
        values = [list(item.values()) for item in rows]
        update_set = ", ".join([f"{column} = EXCLUDED.{column}" for column in columns if column != conflict_col])
        query = f"""
            INSERT INTO {table} ({', '.join(columns)})
            VALUES %s
            ON CONFLICT ({conflict_col})
            DO UPDATE SET {update_set}
        """
        with conn.cursor() as cur:
            execute_values(cur, query, values)
        conn.commit()
        return len(rows)
    except Exception as exc:
        conn.rollback()
        log(f"  [DB ERROR] Upsert failed on {table}: {exc}")
        return 0


def get_current_quarter_label():
    month = datetime.now().month
    year = datetime.now().year
    if month <= 3:
        return f"Q1 {year}", f"{year}-03-31"
    elif month <= 6:
        return f"Q2 {year}", f"{year}-06-30"
    elif month <= 9:
        return f"Q3 {year}", f"{year}-09-30"
    else:
        return f"Q4 {year}", f"{year}-12-31"


def extract_financial_value(facts, concept, form_types=None):
    """
    Pull the most recent reported value for an XBRL concept
    from SEC EDGAR company facts JSON.
    Returns (value, filed_date, form_type) or (None, None, None)
    """
    if form_types is None:
        form_types = ["10-K", "10-Q"]
    try:
        us_gaap = facts.get("facts", {}).get("us-gaap", {})
        concept_data = us_gaap.get(concept, {})
        units = concept_data.get("units", {})
        usd_entries = units.get("USD", [])
        filtered = [
            entry
            for entry in usd_entries
            if entry.get("form") in form_types and entry.get("val") is not None
        ]
        if not filtered:
            return None, None, None
        filtered.sort(key=lambda item: item.get("filed", ""), reverse=True)
        latest = filtered[0]
        return latest.get("val"), latest.get("filed"), latest.get("form")
    except Exception:
        return None, None, None


def normalize_ticker(raw_symbol):
    try:
        symbol = str(raw_symbol or "").upper().strip()
        symbol = symbol.replace(".", "")
        if not symbol:
            return None
        if symbol.isnumeric():
            return None
        if len(symbol) > 5:
            return None
        if not re.match(r"^[A-Z0-9\-]+$", symbol):
            return None
        return symbol
    except Exception:
        return None


def safe_ratio(num, denom):
    try:
        if num is None or denom in (None, 0):
            return None
        return round(float(num) / float(denom), 6)
    except Exception:
        return None


def parse_date_or_none(raw_date):
    try:
        if not raw_date:
            return None
        return datetime.strptime(str(raw_date)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def main():
    for env_var in REQUIRED_ENV_VARS:
        if not os.environ.get(env_var):
            print(f"[FATAL] Missing required env var: {env_var}")
            print("Add it to your .env file or Render environment.")
            sys.exit(1)

    job_id = str(uuid.uuid4())[:8]
    job_start = datetime.now()

    log("=" * 65)
    log("HALAL STOCK CHECKER — FULL US STOCK POPULATION")
    log(f"Job ID:   {job_id}")
    log(f"Start:    {job_start.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Dry Run:  {DRY_RUN}")
    log(f"Test Mode:{TEST_MODE} (first 20 tickers only)")
    log(f"Flags:    {prefix}{dry_prefix}{test_prefix}".strip())
    log("=" * 65)

    conn = None
    sec_map = {}
    all_tickers = []

    try:
        try:
            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            log("PostgreSQL connection established.")
        except Exception as exc:
            log(f"[FATAL] Cannot connect to PostgreSQL: {exc}")
            sys.exit(1)

        # STEP 3 — SEC ticker map
        try:
            sec_tickers_url = "https://www.sec.gov/files/company_tickers.json"
            log("Downloading SEC EDGAR full company tickers map...")
            raw = sec_get(sec_tickers_url)
            if not raw:
                log("[FATAL] Cannot load SEC tickers map. Exiting.")
                sys.exit(1)

            if isinstance(raw, list):
                iterable = raw
            elif isinstance(raw, dict):
                iterable = raw.values()
            else:
                iterable = []

            for entry in iterable:
                try:
                    symbol = normalize_ticker(entry.get("ticker", ""))
                    if symbol:
                        sec_map[symbol] = {
                            "cik": str(entry.get("cik_str", "")).zfill(10),
                            "name": entry.get("title", ""),
                        }
                except Exception as exc:
                    log(f"  [WARN] SEC map entry parse failed: {exc}")
            log(f"SEC map loaded: {len(sec_map)} tickers.")
        except Exception as exc:
            log(f"[FATAL] SEC map build failed: {exc}")
            sys.exit(1)

        # STEP 4 — build master ticker list
        existing_db_tickers = []
        yfinance_exchange_tickers = []
        valid_exchanges = [
            "NYQ",
            "NMS",
            "NGM",
            "NCM",
            "ASE",
            "PCX",
            "NYSEARCA",
            "BTS",
            "OTC",
            "OTCBB",
        ]
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT ticker_symbol FROM stocks")
                existing_db_tickers = [normalize_ticker(row[0]) for row in cur.fetchall() if normalize_ticker(row[0])]
        except Exception as exc:
            log(f"  [WARN] Could not load existing DB tickers from stocks: {exc}")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ticker_symbol FROM stocks "
                    "WHERE UPPER(COALESCE(exchange, '')) = ANY(%s)",
                    (valid_exchanges,),
                )
                yfinance_exchange_tickers = [normalize_ticker(row[0]) for row in cur.fetchall() if normalize_ticker(row[0])]
        except Exception as exc:
            log(f"  [WARN] Could not load yfinance exchange-filtered tickers: {exc}")

        merged = set()
        try:
            for symbol in list(sec_map.keys()) + existing_db_tickers + yfinance_exchange_tickers:
                normalized = normalize_ticker(symbol)
                if normalized:
                    merged.add(normalized)
        except Exception as exc:
            log(f"  [WARN] Ticker merge issue: {exc}")

        all_tickers = sorted(list(merged))
        if TEST_MODE:
            all_tickers = all_tickers[:20]
            log("[TEST MODE] Limited to first 20 tickers.")

        stats["total_tickers"] = len(all_tickers)
        log(f"Master ticker list built: {stats['total_tickers']} unique US tickers.")

        # STEP 5 — ticker_sic
        log("Populating ticker_sic table...")
        sic_rows = []
        processed = 0
        for ticker in all_tickers:
            try:
                entry = sec_map.get(ticker.upper())
                if not entry:
                    log(f"  [SKIP] No SEC entry for {ticker}")
                    stats["cik_missing"] += 1
                    stats["skipped_tickers"].append(ticker)
                    continue

                cik = entry.get("cik", "")
                if not cik:
                    log(f"  [SKIP] Missing CIK in SEC map for {ticker}")
                    stats["cik_missing"] += 1
                    stats["skipped_tickers"].append(ticker)
                    continue

                submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
                data = sec_get(submissions_url)
                if not data:
                    stats["cik_missing"] += 1
                    stats["failed_tickers"].append(ticker)
                    continue

                sic_rows.append(
                    {
                        "ticker_symbol": ticker.upper(),
                        "cik_number": cik,
                        "sic_code": str(data.get("sic", "")),
                        "sic_description": data.get("sicDescription", ""),
                        "company_name": data.get("name", entry.get("name", "")),
                        "last_updated": datetime.now(),
                    }
                )

                processed += 1
                if processed % SEC_BATCH_PAUSE_COUNT == 0:
                    upserted = db_upsert(conn, "ticker_sic", sic_rows, "ticker_symbol")
                    log(
                        f"  [{processed}/{stats['total_tickers']}] ticker_sic: "
                        f"{upserted} rows upserted. Pausing {SEC_BATCH_PAUSE}s..."
                    )
                    sic_rows = []
                    time.sleep(SEC_BATCH_PAUSE)
            except Exception as exc:
                log(f"  [ERROR] ticker_sic processing failed for {ticker}: {exc}")
                stats["failed_tickers"].append(ticker)

        if sic_rows:
            try:
                upserted = db_upsert(conn, "ticker_sic", sic_rows, "ticker_symbol")
                log(f"  Final flush: {upserted} rows upserted.")
            except Exception as exc:
                log(f"  [ERROR] ticker_sic final flush failed: {exc}")

        log(f"ticker_sic population complete. Skipped: {stats['cik_missing']} (no CIK found).")

        # STEP 6 — SEC financials
        log("Fetching SEC EDGAR financial data for all tickers...")
        xbrl_concepts = {
            "total_revenue": [
                "Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet",
            ],
            "total_debt": [
                "LongTermDebt",
                "LongTermDebtAndCapitalLeaseObligations",
                "DebtAndCapitalLeaseObligations",
            ],
            "total_assets": [
                "Assets",
            ],
            "cash_and_equivalents": [
                "CashAndCashEquivalentsAtCarryingValue",
                "CashCashEquivalentsAndShortTermInvestments",
            ],
            "interest_income": [
                "InterestAndDividendIncomeOperating",
                "InterestIncomeOperating",
                "InvestmentIncomeInterest",
                "InterestAndOtherIncome",
            ],
            "other_income": [
                "NonoperatingIncomeExpense",
                "OtherNonoperatingIncomeExpense",
                "OtherIncome",
            ],
            "reserve_income": [
                "RevenueFromReserves",
                "ReserveIncome",
                "InterestIncomeFromSegregatedAssets",
            ],
        }

        financial_rows = []
        processed = 0
        for ticker in all_tickers:
            try:
                time.sleep(TICKER_DELAY)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT cik_number FROM ticker_sic WHERE ticker_symbol = %s",
                        (ticker.upper(),),
                    )
                    result = cur.fetchone()
            except Exception as exc:
                log(f"  [DB ERROR] CIK lookup for {ticker}: {exc}")
                stats["sec_failed"] += 1
                stats["failed_tickers"].append(ticker)
                continue

            if not result or not result[0]:
                log(f"  [SKIP] No CIK for {ticker}")
                stats["sec_skipped"] += 1
                continue

            cik = result[0]
            facts_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

            try:
                facts = sec_get(facts_url)
                if not facts:
                    raise ValueError("Empty SEC EDGAR response")

                extracted = {}
                for field, concepts in xbrl_concepts.items():
                    for concept in concepts:
                        value, filed, form = extract_financial_value(facts, concept)
                        if value is not None:
                            extracted[field] = value
                            extracted["filing_date"] = filed
                            extracted["filing_form"] = form
                            break

                total_revenue = extracted.get("total_revenue")
                total_debt = extracted.get("total_debt")
                total_assets = extracted.get("total_assets")
                cash = extracted.get("cash_and_equivalents")
                interest = (
                    extracted.get("interest_income")
                    or extracted.get("other_income")
                    or extracted.get("reserve_income")
                    or 0
                )

                debt_ratio = safe_ratio(total_debt, total_assets)
                impermissible_ratio = safe_ratio(interest, total_revenue)
                cash_ratio = safe_ratio(cash, total_assets)

                halal_status = "Halal"
                threshold = {"debt": 0.33, "impermissible": 0.05, "cash": 0.33}
                buffer = 0.10

                def check_ratio(ratio, ratio_threshold):
                    if ratio is None:
                        return "Unknown"
                    if ratio > ratio_threshold:
                        return "Non-Halal"
                    if ratio > ratio_threshold * (1 - buffer):
                        return "Questionable"
                    return "Halal"

                statuses = [
                    check_ratio(debt_ratio, threshold["debt"]),
                    check_ratio(impermissible_ratio, threshold["impermissible"]),
                    check_ratio(cash_ratio, threshold["cash"]),
                ]

                if "Non-Halal" in statuses:
                    halal_status = "Non-Halal"
                elif "Questionable" in statuses or "Unknown" in statuses:
                    halal_status = "Questionable"
                else:
                    halal_status = "Halal"

                quarter_label, _ = get_current_quarter_label()
                filing_date = parse_date_or_none(extracted.get("filing_date"))

                financial_rows.append(
                    {
                        "ticker_symbol": ticker.upper(),
                        "total_revenue": total_revenue,
                        "total_debt": total_debt,
                        "total_assets": total_assets,
                        "cash_and_equivalents": cash,
                        "interest_income": interest,
                        "impermissible_income": interest,
                        "debt_ratio": debt_ratio,
                        "impermissible_ratio": impermissible_ratio,
                        "cash_ratio": cash_ratio,
                        "halal_status": halal_status,
                        "filing_date": filing_date,
                        "fiscal_quarter": quarter_label,
                        "fiscal_year": datetime.now().year,
                        "last_updated": datetime.now(),
                    }
                )

                stats["sec_success"] += 1
                if halal_status is None:
                    stats["halal_missing"] += 1
                log(
                    f"  [OK] {ticker} → {halal_status} "
                    f"(debt:{debt_ratio}, impermissible:{impermissible_ratio}, cash:{cash_ratio})"
                )

            except Exception as exc:
                log(f"  [ERROR] SEC financial fetch failed for {ticker}: {exc}")
                stats["sec_failed"] += 1
                stats["failed_tickers"].append(ticker)

            processed += 1
            if processed % SEC_BATCH_PAUSE_COUNT == 0:
                upserted = db_upsert(conn, "financial_data", financial_rows, "ticker_symbol")
                log(
                    f"  [{processed}/{stats['total_tickers']}] financial_data: "
                    f"{upserted} rows. Pausing {SEC_BATCH_PAUSE}s..."
                )
                financial_rows = []
                time.sleep(SEC_BATCH_PAUSE)

        if financial_rows:
            upserted = db_upsert(conn, "financial_data", financial_rows, "ticker_symbol")
            log(f"  Final flush: {upserted} rows upserted.")

        log(
            f"SEC financial data complete. Success: {stats['sec_success']}, "
            f"Failed: {stats['sec_failed']}, Skipped: {stats['sec_skipped']}"
        )

        # STEP 7 — yfinance population
        log("Fetching yfinance market and profile data...")
        stock_rows = []
        batches = [
            all_tickers[index:index + YFINANCE_BATCH_SIZE]
            for index in range(0, len(all_tickers), YFINANCE_BATCH_SIZE)
        ]

        for batch_num, batch in enumerate(batches, 1):
            try:
                log(f"  yfinance batch {batch_num}/{len(batches)} ({len(batch)} tickers)...")
                batch_data = yf_fetch_batch(batch)
                if batch_data is None:
                    log("  [WARN] Batch download returned no data.")
                else:
                    # Keep reference for optional inspection/debug usage.
                    _ = batch_data

                for ticker in batch:
                    try:
                        info = yf_fetch_single(ticker)
                        if not info:
                            stats["yfinance_failed"] += 1
                            if ticker not in stats["failed_tickers"]:
                                stats["failed_tickers"].append(ticker)
                            continue

                        market_cap = info.get("marketCap")
                        if not market_cap:
                            stats["market_cap_missing"] += 1

                        country = info.get("country", "")
                        exchange = info.get("exchange", "")

                        stock_rows.append(
                            {
                                "ticker_symbol": ticker.upper(),
                                "company_name": info.get("longName", ""),
                                "sector": info.get("sector", ""),
                                "industry": info.get("industry", ""),
                                "country": country,
                                "exchange": exchange,
                                "market_cap": market_cap,
                                "stock_price": info.get("regularMarketPrice"),
                                "shares_outstanding": info.get("sharesOutstanding"),
                                "dividend_yield": info.get("dividendYield"),
                                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                                "last_updated": datetime.now(),
                            }
                        )
                        stats["yfinance_success"] += 1

                        if market_cap:
                            log(f"  [OK] yfinance: {ticker} — ${float(market_cap):,.0f} market cap")
                        else:
                            log(f"  [OK] yfinance: {ticker} — no market cap")

                    except Exception as exc:
                        log(f"  [ERROR] yfinance failed for {ticker}: {exc}")
                        stats["yfinance_failed"] += 1
                        if ticker not in stats["failed_tickers"]:
                            stats["failed_tickers"].append(ticker)

                if stock_rows:
                    upserted = db_upsert(conn, "stocks", stock_rows, "ticker_symbol")
                    log(f"  Batch {batch_num}: {upserted} rows upserted.")
                    stock_rows = []

                log(f"  Batch {batch_num} done. Pausing {YFINANCE_BATCH_DELAY}s...")
                time.sleep(YFINANCE_BATCH_DELAY)
            except Exception as exc:
                log(f"  [ERROR] yfinance batch loop failed for batch {batch_num}: {exc}")

        log(
            f"yfinance complete. Success: {stats['yfinance_success']}, "
            f"Failed: {stats['yfinance_failed']}, Market cap missing: {stats['market_cap_missing']}"
        )

        # STEP 8 — Ethical databases
        log("Loading company names from stocks table for matching...")
        db_companies = {}
        company_names = []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ticker_symbol, company_name FROM stocks WHERE company_name IS NOT NULL"
                )
                db_companies = {row[1]: row[0] for row in cur.fetchall() if row and row[0] and row[1]}
            company_names = list(db_companies.keys())
            log(f"  Loaded {len(company_names)} company names.")
        except Exception as exc:
            log(f"  [ERROR] Could not load company names: {exc}")
            company_names = []

        ethical_databases = [
            {
                "key": "bds",
                "name": "Official BDS Target List",
                "table": "ethical_bds",
                "source_url": "https://bdsmovement.net/get-involved/what-to-boycott",
                "csv_path": DATA_DIR / "bds_targets.csv",
                "name_col": "company_name",
            },
            {
                "key": "afsc",
                "name": "AFSC Investigate Database",
                "table": "ethical_afsc",
                "source_url": "https://investigate.afsc.org",
                "csv_path": DATA_DIR / "afsc_companies.csv",
                "name_col": "company_name",
            },
            {
                "key": "un_ohchr",
                "name": "UN OHCHR Database",
                "table": "ethical_un_ohchr",
                "source_url": "https://www.ohchr.org/en/hr-bodies/hrc/sessions/regular-session/database",
                "csv_path": DATA_DIR / "un_ohchr_companies.csv",
                "name_col": "company_name",
            },
            {
                "key": "who_profits",
                "name": "Who Profits Database",
                "table": "ethical_who_profits",
                "source_url": "https://whoprofits.org/companies/",
                "csv_path": DATA_DIR / "who_profits_companies.csv",
                "name_col": "company_name",
            },
        ]

        for ethical_db in ethical_databases:
            log(f"Processing: {ethical_db['name']}...")
            time.sleep(ETHICAL_DB_DELAY)
            source_companies = []

            # Try live fetch first
            try:
                response = requests.get(
                    ethical_db["source_url"],
                    timeout=20,
                    headers={"User-Agent": os.environ["SEC_EDGAR_USER_AGENT"]},
                )
                if response.status_code == 200:
                    text = response.text
                    matches = re.findall(
                        r"<td[^>]*>([\w\s\.,&\-\(\)]+)</td>|<li[^>]*>([\w\s\.,&\-\(\)]+)</li>",
                        text,
                    )
                    source_companies = [
                        (item[0] or item[1]).strip()
                        for item in matches
                        if (item[0] or item[1]).strip() and len((item[0] or item[1]).strip()) > 3
                    ]
                    source_companies = list(dict.fromkeys(source_companies))
                    log(f"  Live fetch: {len(source_companies)} candidates found.")
            except Exception as exc:
                log(f"  Live fetch failed: {exc}. Trying CSV fallback...")

            # CSV fallback
            if not source_companies:
                try:
                    csv_path = ethical_db["csv_path"]
                    if csv_path.exists():
                        with csv_path.open("r", encoding="utf-8") as handle:
                            reader = csv.DictReader(handle)
                            source_companies = []
                            for row in reader:
                                name_value = (row.get(ethical_db["name_col"]) or "").strip()
                                if name_value and not name_value.startswith("#"):
                                    source_companies.append(name_value)
                        log(f"  CSV fallback: {len(source_companies)} companies loaded.")
                    else:
                        log(f"  [SKIP] No CSV fallback found at {csv_path}. Skipping {ethical_db['name']}.")
                        continue
                except Exception as exc:
                    log(f"  [ERROR] CSV fallback failed: {exc}. Skipping {ethical_db['name']}.")
                    continue

            if not source_companies or not company_names:
                log(f"  [SKIP] Nothing to match for {ethical_db['name']}.")
                continue

            ethical_rows = []
            matched_count = 0
            for company in source_companies:
                try:
                    match = fuzz_process.extractOne(
                        company,
                        company_names,
                        scorer=fuzz.token_sort_ratio,
                    )
                    if match and match[1] >= (FUZZY_MATCH_THRESHOLD * 100):
                        matched_name = match[0]
                        ticker = db_companies[matched_name]
                        ethical_rows.append(
                            {
                                "ticker_symbol": ticker,
                                "company_name": company,
                                "listed": True,
                                "match_confidence": round(match[1] / 100, 4),
                                "last_checked": datetime.now(),
                            }
                        )
                        matched_count += 1
                        log(f"  [MATCH] {company} → {ticker} ({match[1]:.1f}% confidence)")
                except Exception as exc:
                    log(f"  [ERROR] Fuzzy match failed for '{company}': {exc}")

            upserted = db_upsert(conn, ethical_db["table"], ethical_rows, "ticker_symbol")
            stats["ethical_matches"][ethical_db["key"]] = upserted
            log(f"  {ethical_db['name']}: {matched_count} matches found, {upserted} upserted.")

        # STEP 9 — validation
        log("Running post-population validation...")
        validation_queries = [
            (
                "Tickers with no financial data",
                "SELECT s.ticker_symbol FROM stocks s "
                "LEFT JOIN financial_data f ON s.ticker_symbol = f.ticker_symbol "
                "WHERE f.ticker_symbol IS NULL LIMIT 20",
            ),
            (
                "Tickers with missing halal status",
                "SELECT ticker_symbol FROM financial_data WHERE halal_status IS NULL LIMIT 20",
            ),
            (
                "Tickers with no market cap",
                "SELECT ticker_symbol FROM stocks WHERE market_cap IS NULL OR market_cap = 0 LIMIT 20",
            ),
            (
                "Tickers with no CIK",
                "SELECT ticker_symbol FROM ticker_sic WHERE cik_number IS NULL OR cik_number = '' LIMIT 20",
            ),
            (
                "Total stocks in DB",
                "SELECT COUNT(*) FROM stocks",
            ),
            (
                "Total financial records",
                "SELECT COUNT(*) FROM financial_data",
            ),
            (
                "Halal status breakdown",
                "SELECT halal_status, COUNT(*) FROM financial_data "
                "GROUP BY halal_status ORDER BY COUNT(*) DESC",
            ),
        ]

        for label, query in validation_queries:
            try:
                with conn.cursor() as cur:
                    cur.execute(query)
                    results = cur.fetchall()
                log(f"  {label}: {results}")
            except Exception as exc:
                log(f"  [ERROR] Validation failed ({label}): {exc}")

    except Exception as exc:
        log(f"[ERROR] Unhandled main loop exception: {exc}")
    finally:
        job_end = datetime.now()
        duration = job_end - job_start
        failed_pct = (
            len(set(stats["failed_tickers"])) / stats["total_tickers"] * 100
            if stats["total_tickers"] > 0
            else 0
        )
        job_status = "SUCCESS" if failed_pct == 0 else "PARTIAL" if failed_pct < 10 else "FAILED"

        log("=" * 65)
        log(f"POPULATION COMPLETE — {job_status}")
        log(f"Job ID:              {job_id}")
        log(f"Total duration:      {duration}")
        log(f"Total tickers:       {stats['total_tickers']}")
        log(f"SEC success:         {stats['sec_success']}")
        log(f"SEC failed:          {stats['sec_failed']}")
        log(f"SEC skipped:         {stats['sec_skipped']}")
        log(f"yfinance success:    {stats['yfinance_success']}")
        log(f"yfinance failed:     {stats['yfinance_failed']}")
        log(f"Market cap missing:  {stats['market_cap_missing']}")
        log(f"CIK missing:         {stats['cik_missing']}")
        log("Ethical matches:")
        log(f"  BDS:               {stats['ethical_matches']['bds']}")
        log(f"  AFSC:              {stats['ethical_matches']['afsc']}")
        log(f"  UN OHCHR:          {stats['ethical_matches']['un_ohchr']}")
        log(f"  Who Profits:       {stats['ethical_matches']['who_profits']}")
        log(f"Failed tickers:      {list(set(stats['failed_tickers']))[:20]}")
        log("=" * 65)

        if conn is not None:
            try:
                conn.close()
            except Exception as exc:
                log(f"[WARN] Failed to close DB connection cleanly: {exc}")


if __name__ == "__main__":
    main()
