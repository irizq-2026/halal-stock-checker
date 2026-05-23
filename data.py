"""Data fetching layer for Halal Stock Checker."""

from __future__ import annotations

import re
from typing import Any

import yfinance as yf

NON_HALAL_KEYWORDS = ("insurance", "gambling", "alcohol", "tobacco")
EXCLUDE_LABEL_PATTERNS = ("minority interest", "noncontrolling interest")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return None


def _is_interest_income_line(label: str) -> bool:
    label_lower = label.lower()
    if any(ex in label_lower for ex in EXCLUDE_LABEL_PATTERNS):
        return False
    interest_phrases = (
        "interest income",
        "interest revenue",
        "net interest income",
        "interest and dividend",
    )
    return any(p in label_lower for p in interest_phrases)


def _matches_non_halal_label(label: str) -> bool:
    label_lower = label.lower()
    if any(ex in label_lower for ex in EXCLUDE_LABEL_PATTERNS):
        return False
    if _is_interest_income_line(label):
        return True
    return any(kw in label_lower for kw in NON_HALAL_KEYWORDS)


def _financials_value(financials, keyword: str) -> float:
    if financials is None or financials.empty:
        return 0.0
    total = 0.0
    found = False
    for label in financials.index:
        label_str = str(label)
        if keyword.lower() == "interest":
            if not _is_interest_income_line(label_str):
                continue
        elif keyword.lower() not in label_str.lower():
            continue
        try:
            val = financials.loc[label].iloc[0]
            fval = _to_float(val)
            if fval is not None:
                total += abs(fval)
                found = True
        except (IndexError, KeyError, TypeError):
            continue
    return total if found else 0.0


def _sum_non_halal_income(financials) -> float:
    if financials is None or financials.empty:
        return 0.0
    total = 0.0
    seen_rows: set[str] = set()
    for label in financials.index:
        label_str = str(label)
        if not _matches_non_halal_label(label_str):
            continue
        if label_str in seen_rows:
            continue
        seen_rows.add(label_str)
        try:
            val = financials.loc[label].iloc[0]
            fval = _to_float(val)
            if fval is not None:
                total += abs(fval)
        except (IndexError, KeyError, TypeError):
            continue
    return total


def fetch_stock_data(symbol: str) -> dict | None:
    try:
        symbol = symbol.strip().upper()
        if not symbol or not re.match(r"^[A-Z.\-]{1,10}$", symbol):
            return None

        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        financials = ticker.financials

        company_name = info.get("longName") or info.get("shortName") or symbol
        sector = info.get("sector") or "Unknown"
        industry = info.get("industry") or ""

        market_cap = _to_float(info.get("marketCap"))
        if market_cap is None or market_cap == 0:
            return {"error": "Market cap unavailable"}

        total_debt = _to_float(info.get("totalDebt"))
        cash = _to_float(info.get("totalCash"))
        total_revenue = _to_float(info.get("totalRevenue"))

        interest_income = _financials_value(financials, "Interest")
        non_halal_income = _sum_non_halal_income(financials)

        return {
            "symbol": symbol,
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "market_cap": market_cap,
            "total_debt": total_debt if total_debt is not None else 0.0,
            "cash": cash if cash is not None else 0.0,
            "total_revenue": total_revenue,
            "interest_income": interest_income,
            "non_halal_income": non_halal_income,
        }
    except Exception:
        return None