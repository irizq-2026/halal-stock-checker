"""Cache-aside per-ticker price refresh using yfinance."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import yfinance as yf
from sqlalchemy import text
from sqlalchemy.orm import Session

from db import SessionLocal

LOGGER = logging.getLogger(__name__)

PRICE_CACHE_TTL = timedelta(hours=24)

_LOCKS_GUARD = threading.Lock()
_TICKER_LOCKS: dict[str, threading.Lock] = {}


def _normalize_ticker(ticker: str) -> str:
    return (ticker or "").strip().upper()


def _get_ticker_lock(ticker: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _TICKER_LOCKS.get(ticker)
        if lock is None:
            lock = threading.Lock()
            _TICKER_LOCKS[ticker] = lock
        return lock


def _load_latest_price_row(session: Session, ticker: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                SELECT
                    ticker,
                    close_price,
                    price_date,
                    shares_outstanding,
                    market_cap,
                    updated_at
                FROM stock_prices
                WHERE ticker = :ticker
                ORDER BY price_date DESC, updated_at DESC
                LIMIT 1
                """
            ),
            {"ticker": ticker},
        )
        .mappings()
        .first()
    )
    if not row:
        return None
    return dict(row)


def _is_fresh(row: dict[str, Any], ttl: timedelta) -> bool:
    updated_at = row.get("updated_at")
    close_price = row.get("close_price")
    if updated_at is None or close_price is None:
        return False

    if updated_at.tzinfo is not None:
        updated_utc = updated_at.astimezone(UTC).replace(tzinfo=None)
    else:
        updated_utc = updated_at
    return (datetime.utcnow() - updated_utc) < ttl


def _fetch_latest_price_from_yahoo(ticker: str) -> tuple[float, Any]:
    ticker_client = yf.Ticker(ticker)
    history = ticker_client.history(period="1d", interval="1d", auto_adjust=False)
    if history.empty or "Close" not in history.columns:
        # Weekend/holiday fallback still keeps this single-ticker.
        history = ticker_client.history(period="5d", interval="1d", auto_adjust=False)
    if history.empty or "Close" not in history.columns:
        raise RuntimeError(f"Yahoo price history unavailable for {ticker}")

    close_series = history["Close"].dropna()
    if close_series.empty:
        raise RuntimeError(f"Yahoo close price missing for {ticker}")

    close_price = float(close_series.iloc[-1])
    index_value = close_series.index[-1]
    if hasattr(index_value, "date"):
        price_date = index_value.date()
    else:
        raise RuntimeError(f"Yahoo price date missing for {ticker}")
    return close_price, price_date


def _load_shares_outstanding(session: Session, ticker: str) -> int | None:
    row = (
        session.execute(
            text(
                """
                SELECT shares_outstanding
                FROM sec_shares
                WHERE ticker = :ticker
                LIMIT 1
                """
            ),
            {"ticker": ticker},
        )
        .mappings()
        .first()
    )
    shares = (row or {}).get("shares_outstanding")
    if shares is None:
        return None
    try:
        shares_int = int(shares)
    except (TypeError, ValueError):
        return None
    return shares_int if shares_int > 0 else None


def _upsert_price_row(session: Session, ticker: str, close_price: float, price_date: Any) -> None:
    shares_outstanding = _load_shares_outstanding(session, ticker)
    market_cap = round(close_price * shares_outstanding, 2) if shares_outstanding else None
    session.execute(
        text(
            """
            INSERT INTO stock_prices (
                ticker,
                close_price,
                price_date,
                shares_outstanding,
                market_cap,
                updated_at
            )
            VALUES (
                :ticker,
                :close_price,
                :price_date,
                :shares_outstanding,
                :market_cap,
                NOW()
            )
            ON CONFLICT (ticker, price_date)
            DO UPDATE SET
                close_price = EXCLUDED.close_price,
                shares_outstanding = COALESCE(EXCLUDED.shares_outstanding, stock_prices.shares_outstanding),
                market_cap = CASE
                    WHEN COALESCE(EXCLUDED.shares_outstanding, stock_prices.shares_outstanding) IS NOT NULL
                    THEN EXCLUDED.close_price * COALESCE(EXCLUDED.shares_outstanding, stock_prices.shares_outstanding)
                    ELSE stock_prices.market_cap
                END,
                updated_at = NOW()
            """
        ),
        {
            "ticker": ticker,
            "close_price": close_price,
            "price_date": price_date,
            "shares_outstanding": shares_outstanding,
            "market_cap": market_cap,
        },
    )
    session.commit()


def get_cached_or_refresh_price_row(
    ticker: str,
    *,
    cache_ttl: timedelta = PRICE_CACHE_TTL,
) -> dict[str, Any] | None:
    """
    Cache-aside read for latest per-ticker price row.

    - Uses DB row when it is fresh (<24h old)
    - Otherwise refreshes from yfinance for only this ticker
    - On yfinance failure, returns last known DB row when available
    """
    normalized_ticker = _normalize_ticker(ticker)
    if not normalized_ticker:
        return None

    session: Session = SessionLocal()
    try:
        cached = _load_latest_price_row(session, normalized_ticker)
        if cached and _is_fresh(cached, cache_ttl):
            return cached

        ticker_lock = _get_ticker_lock(normalized_ticker)
        with ticker_lock:
            cached = _load_latest_price_row(session, normalized_ticker)
            if cached and _is_fresh(cached, cache_ttl):
                return cached

            try:
                close_price, price_date = _fetch_latest_price_from_yahoo(normalized_ticker)
                _upsert_price_row(session, normalized_ticker, close_price, price_date)
                refreshed = _load_latest_price_row(session, normalized_ticker)
                if refreshed:
                    return refreshed
            except Exception:
                session.rollback()
                LOGGER.exception("yfinance refresh failed for ticker=%s", normalized_ticker)
            return cached
    finally:
        session.close()
