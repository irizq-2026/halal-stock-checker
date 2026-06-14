"""Local Postgres read layer for Halal Stock Checker UI."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session

from db import SessionLocal
from sec_refresh import latest_cached_screen_row
from services.yfinance_price_cache import get_cached_or_refresh_price_row

LOGGER = logging.getLogger(__name__)


class TransientDataError(Exception):
    """Temporary storage issue — callers can retry later."""


class DatabaseUnavailableError(TransientDataError):
    """Database is unreachable or missing required schema."""


class CachedDataNotReadyError(Exception):
    """Ticker has not been loaded into the local SEC cache yet."""


def _is_valid_symbol(symbol: str) -> bool:
    return bool(re.match(r"^[A-Z.\-]{1,10}$", symbol or ""))


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def _build_stock_payload(company: Any, filing: Any, normalized: Any, result: Any) -> dict[str, Any]:
    interest_income = _to_float(normalized.interest_income) or 0.0
    total_revenue = _to_float(normalized.total_revenue)
    source_metadata = normalized.source_metadata_json or {}
    ethical_insights = {}
    if isinstance(source_metadata.get("ethical_insights"), dict):
        ethical_insights = source_metadata.get("ethical_insights") or {}
    elif isinstance(result.mapped_tags_json, dict) and isinstance(result.mapped_tags_json.get("ethical_insights"), dict):
        # Backward-compatible fallback for rows populated from result metadata.
        ethical_insights = result.mapped_tags_json.get("ethical_insights") or {}
    return {
        "symbol": company.ticker,
        "company_name": company.company_name,
        "sector": company.sector or "",
        "industry": company.industry or "",
        "market_cap": _to_float(normalized.market_cap),
        "total_debt": _to_float(normalized.total_debt) or 0.0,
        "cash": _to_float(normalized.cash_and_equivalents) or 0.0,
        "total_revenue": total_revenue,
        "interest_income": interest_income,
        # Preserve existing screening behavior by feeding non-halal income field.
        "non_halal_income": interest_income,
        "ethical_insights": ethical_insights,
        "_data_source": {
            "name": result.data_source,
            "filing_date": str(result.source_filing_date) if result.source_filing_date else str(filing.filing_date),
            "last_updated": result.last_updated.isoformat() if result.last_updated else None,
            "accession_number": filing.accession_number,
            "filing_type": filing.filing_type,
            "mapped_tags": source_metadata,
        },
    }


def _load_stocks_price_snapshot(session: Session, ticker: str) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                """
                SELECT
                    stock_price,
                    market_cap,
                    shares_outstanding,
                    last_updated
                FROM stocks
                WHERE ticker_symbol = :ticker
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


def fetch_stock_data(symbol: str) -> dict[str, Any] | None:
    """Fetch latest normalized cached financial data from Postgres only."""
    normalized_symbol = (symbol or "").strip().upper()
    if not _is_valid_symbol(normalized_symbol):
        return None

    session: Session = SessionLocal()
    try:
        row = latest_cached_screen_row(session, normalized_symbol)
        if row is None:
            raise CachedDataNotReadyError(
                f"No cached SEC data found for {normalized_symbol}.",
            )
        company, filing, normalized, result = row
        if (result.data_source or "").strip().lower() == "sec_placeholder":
            raise CachedDataNotReadyError(
                f"No recent SEC 10-Q/10-K or company-facts data is available for {normalized_symbol}.",
            )
        payload = _build_stock_payload(company, filing, normalized, result)
        latest_price_row = get_cached_or_refresh_price_row(normalized_symbol) or {}
        stocks_snapshot = _load_stocks_price_snapshot(session, normalized_symbol) or {}

        resolved_close_price = _to_float(latest_price_row.get("close_price"))
        if resolved_close_price is None:
            resolved_close_price = _to_float(stocks_snapshot.get("stock_price"))

        resolved_shares = latest_price_row.get("shares_outstanding")
        if resolved_shares in (None, 0):
            resolved_shares = normalized.shares_outstanding
        if resolved_shares in (None, 0):
            resolved_shares = stocks_snapshot.get("shares_outstanding")

        resolved_market_cap = _to_float(payload.get("market_cap"))
        if resolved_market_cap in (None, 0):
            resolved_market_cap = _to_float(latest_price_row.get("market_cap"))
        if resolved_market_cap in (None, 0):
            resolved_market_cap = _to_float(stocks_snapshot.get("market_cap"))
        if resolved_market_cap in (None, 0):
            shares_value = _to_float(resolved_shares)
            if shares_value not in (None, 0) and resolved_close_price not in (None, 0):
                resolved_market_cap = resolved_close_price * shares_value

        if payload.get("market_cap") in (None, 0) and resolved_market_cap not in (None, 0):
            payload["market_cap"] = resolved_market_cap

        if any(
            value not in (None, 0)
            for value in (
                resolved_market_cap,
                resolved_close_price,
                _to_float(resolved_shares),
            )
        ):
            payload["_data_source"]["market_cap_fallback"] = {
                "source": "stock_prices+stocks",
                "price_date": str(latest_price_row.get("price_date")) if latest_price_row.get("price_date") else None,
                "close_price": resolved_close_price,
                "shares_outstanding": resolved_shares,
                "updated_at": str(latest_price_row.get("updated_at")) if latest_price_row.get("updated_at") else (
                    str(stocks_snapshot.get("last_updated")) if stocks_snapshot.get("last_updated") else None
                ),
            }
        return payload
    except CachedDataNotReadyError:
        raise
    except (OperationalError, ProgrammingError) as exc:
        LOGGER.exception("Database unavailable while reading cached stock data for %s", normalized_symbol)
        raise DatabaseUnavailableError(
            "Local SEC cache is unavailable. Configure DATABASE_URL and ensure tables exist.",
        ) from exc
    except SQLAlchemyError as exc:
        LOGGER.exception("Database error while reading cached stock data for %s", normalized_symbol)
        raise DatabaseUnavailableError(
            "Local SEC cache query failed. Please check database connectivity and schema.",
        ) from exc
    except Exception as exc:
        LOGGER.exception("Failed to fetch cached stock data for %s", normalized_symbol)
        raise TransientDataError(str(exc)) from exc
    finally:
        session.close()


def fetch_company_enrichment(symbol: str) -> dict[str, Any]:
    """Read optional company profile fields from local DB for UI cards."""
    normalized_symbol = (symbol or "").strip().upper()
    if not _is_valid_symbol(normalized_symbol):
        return {"info": {}, "news": [], "cashflow_available": False, "news_available": False}

    session: Session = SessionLocal()
    try:
        row = latest_cached_screen_row(session, normalized_symbol)
        if row is None:
            return {"info": {}, "news": [], "cashflow_available": False, "news_available": False}
        company, _, _, _ = row
        return {
            "info": {
                "website": company.website or "",
                "exchange": company.exchange or "",
                "longBusinessSummary": "",
                "sector": company.sector or "",
                "industry": company.industry or "",
                "longName": company.company_name or "",
            },
            "news": [],
            "cashflow_available": True,
            "news_available": False,
        }
    except Exception:
        return {"info": {}, "news": [], "cashflow_available": False, "news_available": False}
    finally:
        session.close()
