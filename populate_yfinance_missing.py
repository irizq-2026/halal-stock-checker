# ── HOW TO RUN ────────────────────────────────────────────────
#
# Normal run (only missing data):
#   python populate_yfinance_missing.py
#
# Test run (first 50 tickers only — always run this first):
#   python populate_yfinance_missing.py --test
#
# Dry run (log what would happen, no DB writes):
#   python populate_yfinance_missing.py --dry-run
#
# Force re-fetch all tickers even if data exists:
#   python populate_yfinance_missing.py --force
#
# Combine flags:
#   python populate_yfinance_missing.py --test --dry-run
#
# Monitor progress in separate terminal:
#   tail -f yfinance_population_log.txt
#
# Required environment variables:
#   DATABASE_URL  = your PostgreSQL connection string
#
# Estimated runtime:
#   ~9,000 tickers at 1.5s each = ~4 hours
#   Progress reported every 15 minutes automatically
# ─────────────────────────────────────────────────────────────

import os
import sys
import time
import uuid
import yfinance as yf
import psycopg2
from pathlib import Path
from datetime import datetime, timedelta
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

# ── RUN MODE ──────────────────────────────────────────────────
DRY_RUN = "--dry-run" in sys.argv  # log only, no DB writes
TEST_MODE = "--test" in sys.argv  # first 50 tickers only
FORCE_ALL = "--force" in sys.argv  # re-fetch ALL tickers
# even if data exists

# ── RATE LIMITS ───────────────────────────────────────────────
YFINANCE_SINGLE_DELAY = 1.0  # seconds between single fetches
YFINANCE_BATCH_DELAY = 3.0  # seconds between batch downloads
YFINANCE_BATCH_SIZE = 50  # tickers per yf.download() batch
TICKER_DELAY = 0.5  # seconds between each ticker

# ── PROGRESS REPORTING ────────────────────────────────────────
REPORT_INTERVAL_SECS = 900  # 15 minutes

# ── LOGGING ───────────────────────────────────────────────────
LOG_FILE = Path("yfinance_population_log.txt")

# ── STATS ─────────────────────────────────────────────────────
stats = {
    "total_missing": 0,
    "yfinance_success": 0,
    "yfinance_failed": 0,
    "market_cap_missing": 0,
    "price_missing": 0,
    "shares_missing": 0,
    "halal_recalculated": 0,
    "failed_tickers": [],
}


REQUIRED_ENV_VARS = [
    "DATABASE_URL",
]

for var in REQUIRED_ENV_VARS:
    if not os.environ.get(var):
        print(f"[FATAL] Missing required env var: {var}")
        sys.exit(1)


def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def get_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def yf_fetch_single(ticker):
    try:
        time.sleep(YFINANCE_SINGLE_DELAY)
        stock = yf.Ticker(ticker)
        info = stock.info
        if not info or len(info) < 5:
            log(f"  [EMPTY] yfinance returned no data for {ticker}")
            return None
        if (
            info.get("regularMarketPrice") is None
            and info.get("currentPrice") is None
            and info.get("previousClose") is None
        ):
            log(f"  [NO PRICE] yfinance has no price data for {ticker}")
            return None
        return info
    except Exception as exc:
        log(f"  [ERROR] yfinance failed for {ticker}: {exc}")
        return None


def extract_price(info):
    for field in [
        "regularMarketPrice",
        "currentPrice",
        "previousClose",
        "regularMarketPreviousClose",
    ]:
        val = info.get(field)
        if val and val > 0:
            return val
    return None


def extract_market_cap(info):
    for field in [
        "marketCap",
        "enterpriseValue",
    ]:
        val = info.get(field)
        if val and val > 0:
            return val
    price = extract_price(info)
    shares = info.get("sharesOutstanding")
    if price and shares and price > 0 and shares > 0:
        return int(price * shares)
    return None


def db_upsert_stock(conn, row):
    if DRY_RUN:
        log(f"  [DRY RUN] Would update {row['ticker_symbol']}")
        return True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE stocks SET
                    stock_price = CASE
                        WHEN stock_price IS NULL OR stock_price = 0
                        THEN COALESCE(%s, stock_price)
                        ELSE stock_price
                    END,
                    market_cap = CASE
                        WHEN market_cap IS NULL OR market_cap = 0
                        THEN COALESCE(%s, market_cap)
                        ELSE market_cap
                    END,
                    shares_outstanding = CASE
                        WHEN shares_outstanding IS NULL OR shares_outstanding = 0
                        THEN COALESCE(%s, shares_outstanding)
                        ELSE shares_outstanding
                    END,
                    company_name = COALESCE(NULLIF(%s, ''), company_name),
                    sector = COALESCE(NULLIF(%s, ''), sector),
                    industry = COALESCE(NULLIF(%s, ''), industry),
                    country = COALESCE(NULLIF(%s, ''), country),
                    exchange = COALESCE(NULLIF(%s, ''), exchange),
                    dividend_yield = COALESCE(%s, dividend_yield),
                    fifty_two_week_high = COALESCE(%s, fifty_two_week_high),
                    fifty_two_week_low = COALESCE(%s, fifty_two_week_low),
                    last_updated = %s
                WHERE ticker_symbol = %s
                """,
                (
                    row.get("stock_price"),
                    row.get("market_cap"),
                    row.get("shares_outstanding"),
                    row.get("company_name"),
                    row.get("sector"),
                    row.get("industry"),
                    row.get("country"),
                    row.get("exchange"),
                    row.get("dividend_yield"),
                    row.get("fifty_two_week_high"),
                    row.get("fifty_two_week_low"),
                    datetime.now(),
                    row["ticker_symbol"],
                ),
            )
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        log(f"  [DB ERROR] Update failed for {row['ticker_symbol']}: {exc}")
        return False


def recalculate_halal_status(conn, ticker):
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    debt_ratio,
                    impermissible_ratio,
                    cash_ratio,
                    halal_status
                FROM financial_data
                WHERE ticker_symbol = %s
                """,
                (ticker,),
            )
            result = cur.fetchone()

        if not result:
            return

        debt_ratio, imp_ratio, cash_ratio, current_status = result
        if current_status == "Non-Halal":
            return

        thresholds = {
            "debt": 0.33,
            "impermissible": 0.05,
            "cash": 0.33,
        }
        buffer = 0.10

        def check(ratio, threshold):
            if ratio is None:
                return "Unknown"
            if ratio > threshold:
                return "Non-Halal"
            if ratio > threshold * (1 - buffer):
                return "Questionable"
            return "Halal"

        statuses = [
            check(debt_ratio, thresholds["debt"]),
            check(imp_ratio, thresholds["impermissible"]),
            check(cash_ratio, thresholds["cash"]),
        ]

        if "Non-Halal" in statuses:
            new_status = "Non-Halal"
        elif "Questionable" in statuses or "Unknown" in statuses:
            new_status = "Questionable"
        else:
            new_status = "Halal"

        if new_status != current_status:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE financial_data
                    SET halal_status = %s,
                        last_updated = %s
                    WHERE ticker_symbol = %s
                    """,
                    (new_status, datetime.now(), ticker),
                )
            conn.commit()
            log(f"  [RECALC] {ticker}: {current_status} → {new_status}")
            stats["halal_recalculated"] += 1

    except Exception as exc:
        conn.rollback()
        log(f"  [ERROR] Recalculate failed for {ticker}: {exc}")


def progress_report(job_start, processed):
    total = stats["total_missing"]
    remaining = total - processed
    elapsed = datetime.now() - job_start
    rate = processed / max(elapsed.seconds, 1)
    eta_secs = int(remaining / rate) if rate > 0 else 0
    eta_str = str(timedelta(seconds=eta_secs))

    log("─" * 55)
    log("▶ PROGRESS REPORT")
    log(f"  Elapsed:            {elapsed}")
    log(f"  Processed:          {processed}/{total}")
    log(f"  yfinance success:   {stats['yfinance_success']}")
    log(f"  yfinance failed:    {stats['yfinance_failed']}")
    log(
        "  Market cap fixed:   "
        f"{stats['yfinance_success'] - stats['market_cap_missing']}"
    )
    log(f"  Halal recalculated: {stats['halal_recalculated']}")
    log(f"  Estimated ETA:      {eta_str}")
    log("─" * 55)


def main():
    job_id = str(uuid.uuid4())[:8]
    job_start = datetime.now()
    last_report_time = datetime.now()

    log("=" * 55)
    log("YFINANCE MISSING DATA POPULATION")
    log(f"Job ID:    {job_id}")
    log(f"Start:     {job_start.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Dry Run:   {DRY_RUN}")
    log(f"Test Mode: {TEST_MODE} (first 50 tickers only)")
    log(f"Force All: {FORCE_ALL} (re-fetch all tickers)")
    log("=" * 55)

    try:
        conn = get_connection()
        log("PostgreSQL connection established.")
    except Exception as exc:
        log(f"[FATAL] Cannot connect to PostgreSQL: {exc}")
        sys.exit(1)

    try:
        log("Loading tickers with missing yfinance data...")
        try:
            with conn.cursor() as cur:
                if FORCE_ALL:
                    cur.execute(
                        """
                        SELECT ticker_symbol
                        FROM stocks
                        ORDER BY ticker_symbol
                        """
                    )
                    log("  [FORCE] Loading ALL tickers.")
                else:
                    cur.execute(
                        """
                        SELECT s.ticker_symbol
                        FROM stocks s
                        WHERE (
                            s.stock_price IS NULL
                            OR s.stock_price = 0
                            OR s.market_cap IS NULL
                            OR s.market_cap = 0
                            OR s.shares_outstanding IS NULL
                        )
                        AND EXISTS (
                            SELECT 1 FROM financial_data f
                            WHERE f.ticker_symbol = s.ticker_symbol
                        )
                        ORDER BY s.ticker_symbol
                        """
                    )
                missing_tickers = [row[0] for row in cur.fetchall()]
        except Exception as exc:
            log(f"[FATAL] Could not query missing tickers: {exc}")
            conn.close()
            sys.exit(1)

        if TEST_MODE:
            missing_tickers = missing_tickers[:50]
            log("[TEST MODE] Limited to first 50 tickers.")

        stats["total_missing"] = len(missing_tickers)
        log(f"Found {stats['total_missing']} tickers with missing yfinance data.")

        if stats["total_missing"] == 0:
            log("Nothing to do — all tickers have yfinance data.")
            log("Use --force to re-fetch all tickers anyway.")
            conn.close()
            return

        log("Checking for Questionable stocks due to missing market cap...")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT f.ticker_symbol
                    FROM financial_data f
                    JOIN stocks s
                        ON f.ticker_symbol = s.ticker_symbol
                    WHERE f.halal_status = 'Questionable'
                    AND (
                        s.market_cap IS NULL
                        OR s.market_cap = 0
                    )
                    """
                )
                additional = [row[0] for row in cur.fetchall()]

            all_tickers = list(dict.fromkeys(missing_tickers + additional))
            if additional:
                log(
                    f"  Added {len(additional)} Questionable tickers with missing market cap."
                )
            stats["total_missing"] = len(all_tickers)
            log(f"Total tickers to process: {stats['total_missing']}")
        except Exception as exc:
            log(f"  [WARNING] Could not load Questionable tickers: {exc}")
            all_tickers = missing_tickers

        log("Starting yfinance fetch...")
        processed = 0
        batches = [
            all_tickers[i : i + YFINANCE_BATCH_SIZE]
            for i in range(0, len(all_tickers), YFINANCE_BATCH_SIZE)
        ]

        for batch_num, batch in enumerate(batches, 1):
            log(f"  Batch {batch_num}/{len(batches)} ({len(batch)} tickers)...")

            for ticker in batch:
                time.sleep(TICKER_DELAY)
                try:
                    info = yf_fetch_single(ticker)
                    if not info:
                        stats["yfinance_failed"] += 1
                        stats["failed_tickers"].append(ticker)
                        processed += 1
                        continue

                    price = extract_price(info)
                    market_cap = extract_market_cap(info)
                    shares = info.get("sharesOutstanding")

                    if not price:
                        stats["price_missing"] += 1
                    if not market_cap:
                        stats["market_cap_missing"] += 1
                    if not shares:
                        stats["shares_missing"] += 1

                    row = {
                        "ticker_symbol": ticker,
                        "stock_price": price,
                        "market_cap": market_cap,
                        "shares_outstanding": shares,
                        "company_name": info.get("longName", ""),
                        "sector": info.get("sector", ""),
                        "industry": info.get("industry", ""),
                        "country": info.get("country", ""),
                        "exchange": info.get("exchange", ""),
                        "dividend_yield": info.get("dividendYield"),
                        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                    }

                    success = db_upsert_stock(conn, row)
                    if success:
                        stats["yfinance_success"] += 1
                        if market_cap:
                            log(
                                f"  [OK] {ticker} — price: {price}, "
                                f"mktcap: {market_cap:,.0f}"
                            )
                            recalculate_halal_status(conn, ticker)
                        else:
                            log(f"  [OK] {ticker} — price: {price}, mktcap: N/A")
                    else:
                        stats["yfinance_failed"] += 1
                        stats["failed_tickers"].append(ticker)
                except Exception as exc:
                    log(f"  [ERROR] Unexpected error for {ticker}: {exc}")
                    stats["yfinance_failed"] += 1
                    stats["failed_tickers"].append(ticker)

                processed += 1
                elapsed_since = (datetime.now() - last_report_time).seconds
                if elapsed_since >= REPORT_INTERVAL_SECS:
                    progress_report(job_start, processed)
                    last_report_time = datetime.now()

            log(
                f"  Batch {batch_num} complete. "
                f"Pausing {YFINANCE_BATCH_DELAY}s..."
            )
            time.sleep(YFINANCE_BATCH_DELAY)

        log("Running validation...")
        validation_queries = [
            (
                "Stocks still missing price",
                "SELECT COUNT(*) FROM stocks "
                "WHERE stock_price IS NULL OR stock_price = 0",
            ),
            (
                "Stocks still missing market cap",
                "SELECT COUNT(*) FROM stocks "
                "WHERE market_cap IS NULL OR market_cap = 0",
            ),
            (
                "Stocks still missing shares",
                "SELECT COUNT(*) FROM stocks "
                "WHERE shares_outstanding IS NULL",
            ),
            (
                "Halal status breakdown after recalc",
                "SELECT halal_status, COUNT(*) "
                "FROM financial_data "
                "GROUP BY halal_status "
                "ORDER BY COUNT(*) DESC",
            ),
            (
                "Stocks with complete yfinance data",
                "SELECT COUNT(*) FROM stocks "
                "WHERE stock_price > 0 "
                "AND market_cap > 0 "
                "AND shares_outstanding > 0",
            ),
        ]

        for label, query in validation_queries:
            try:
                with conn.cursor() as cur:
                    cur.execute(query)
                    result = cur.fetchall()
                log(f"  {label}: {result}")
            except Exception as exc:
                log(f"  [ERROR] Validation failed ({label}): {exc}")

        job_end = datetime.now()
        duration = job_end - job_start
        failed_pct = (
            len(set(stats["failed_tickers"])) / max(stats["total_missing"], 1) * 100
        )
        job_status = (
            "SUCCESS"
            if failed_pct == 0
            else "PARTIAL"
            if failed_pct < 10
            else "NEEDS ATTENTION"
        )

        log("=" * 55)
        log(f"YFINANCE POPULATION COMPLETE — {job_status}")
        log(f"Job ID:              {job_id}")
        log(f"Duration:            {duration}")
        log(f"Total processed:     {stats['total_missing']}")
        log(f"yfinance success:    {stats['yfinance_success']}")
        log(f"yfinance failed:     {stats['yfinance_failed']}")
        log(f"Price missing:       {stats['price_missing']}")
        log(f"Market cap missing:  {stats['market_cap_missing']}")
        log(f"Shares missing:      {stats['shares_missing']}")
        log(f"Halal recalculated:  {stats['halal_recalculated']}")
        log(f"Failed tickers:      {list(set(stats['failed_tickers']))[:20]}")
        log("=" * 55)

    except Exception as exc:
        log(f"[FATAL] Unexpected failure in main: {exc}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
