"""Local Postgres read layer for Halal Stock Checker UI."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from db import SessionLocal
from sec_refresh import latest_cached_screen_row

LOGGER = logging.getLogger(__name__)


class TransientDataError(Exception):
    """Temporary storage issue — callers can retry later."""


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
        "_data_source": {
            "name": result.data_source,
            "filing_date": str(result.source_filing_date) if result.source_filing_date else str(filing.filing_date),
            "last_updated": result.last_updated.isoformat() if result.last_updated else None,
            "accession_number": filing.accession_number,
            "filing_type": filing.filing_type,
            "mapped_tags": normalized.source_metadata_json or {},
        },
    }


def fetch_stock_data(symbol: str) -> dict[str, Any] | None:
    """Fetch latest normalized cached financial data from Postgres only."""
    normalized_symbol = (symbol or "").strip().upper()
    if not _is_valid_symbol(normalized_symbol):
        return None

    session: Session = SessionLocal()
    try:
        row = latest_cached_screen_row(session, normalized_symbol)
        if row is None:
            return None
        company, filing, normalized, result = row
        return _build_stock_payload(company, filing, normalized, result)
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
