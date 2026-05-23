"""Data fetching layer for Halal Stock Checker."""

from __future__ import annotations

import os
import re
from typing import Any

import pandas as pd
import yfinance as yf

_CACHE_DIR = os.environ.get("YFINANCE_CACHE_DIR", "/tmp/yfinance-cache")
os.makedirs(_CACHE_DIR, exist_ok=True)
try:
    yf.set_tz_cache_location(_CACHE_DIR)
except Exception:
    pass

NON_HALAL_KEYWORDS = ("insurance", "gambling", "alcohol", "tobacco")
EXCLUDE_LABEL_PATTERNS = ("minority interest", "noncontrolling interest")

UNKNOWN_PROFILE_VALUES = frozenset({"", "unknown", "n/a", "na", "none", "—", "-"})


def _clean_profile_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in UNKNOWN_PROFILE_VALUES:
        return ""
    return text


def _parse_quote_summary_block(block: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    asset = block.get("assetProfile") or {}
    summary = block.get("summaryProfile") or {}
    price = block.get("price") or {}
    out["company_name"] = _clean_profile_text(
        price.get("longName")
        or price.get("shortName")
        or summary.get("longName")
        or summary.get("name")
    )
    out["sector"] = _clean_profile_text(
        asset.get("sector") or asset.get("sectorDisp") or summary.get("sector")
    )
    out["industry"] = _clean_profile_text(
        asset.get("industry") or asset.get("industryDisp") or summary.get("industry")
    )
    return out


def _fetch_quote_summary_profile(ticker: yf.Ticker) -> dict[str, str]:
    """Load sector/industry/name via Yahoo quoteSummary (cloud-friendly)."""
    out: dict[str, str] = {}
    symbol = getattr(ticker, "ticker", None) or ""
    if not symbol:
        return out

    dat = getattr(ticker, "_data", None)
    modules = "assetProfile,summaryProfile,price"
    hosts = (
        "https://query2.finance.yahoo.com",
        "https://query1.finance.yahoo.com",
    )

    if dat is not None:
        for host in hosts:
            try:
                url = f"{host}/v10/finance/quoteSummary/{symbol}"
                payload = dat.get_raw_json(url, params={"modules": modules})
                results = payload.get("quoteSummary", {}).get("result") or []
                if results:
                    out = _parse_quote_summary_block(results[0])
                    if out.get("sector") or out.get("industry") or out.get("company_name"):
                        return out
            except Exception:
                continue

        # v7 quote: reliable for company name on some cloud hosts
        try:
            url = "https://query1.finance.yahoo.com/v7/finance/quote"
            payload = dat.get_raw_json(url, params={"symbols": symbol})
            results = payload.get("quoteResponse", {}).get("result") or []
            if results:
                row = results[0]
                if not out.get("company_name"):
                    out["company_name"] = _clean_profile_text(
                        row.get("longName") or row.get("shortName")
                    )
                if not out.get("sector"):
                    out["sector"] = _clean_profile_text(row.get("sector"))
                if not out.get("industry"):
                    out["industry"] = _clean_profile_text(row.get("industry"))
        except Exception:
            pass

    # Last resort: second info fetch (sometimes populates after other calls)
    try:
        info = ticker.info or {}
        if isinstance(info, dict):
            if not out.get("company_name"):
                out["company_name"] = _clean_profile_text(
                    info.get("longName") or info.get("shortName")
                )
            if not out.get("sector"):
                out["sector"] = _clean_profile_text(
                    info.get("sector") or info.get("sectorDisp")
                )
            if not out.get("industry"):
                out["industry"] = _clean_profile_text(
                    info.get("industry") or info.get("industryDisp")
                )
    except Exception:
        pass

    return out


def _resolve_company_profile(
    ticker: yf.Ticker, info: dict, symbol: str
) -> tuple[str, str, str]:
    profile = _fetch_quote_summary_profile(ticker)

    company_name = _clean_profile_text(
        info.get("longName")
        or info.get("shortName")
        or info.get("displayName")
        or profile.get("company_name")
    )
    sector = _clean_profile_text(
        info.get("sector") or info.get("sectorDisp") or profile.get("sector")
    )
    industry = _clean_profile_text(
        info.get("industry") or info.get("industryDisp") or profile.get("industry")
    )

    if not company_name or company_name.upper() == symbol.upper():
        company_name = profile.get("company_name") or company_name

    if not company_name or company_name.upper() == symbol.upper():
        company_name = ""

    return company_name, sector, industry



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


def _df_row_value(df: pd.DataFrame | None, *needles: str) -> float | None:
    if df is None or df.empty:
        return None
    for idx in df.index:
        label = str(idx).lower()
        if any(n.lower() in label for n in needles):
            try:
                val = _to_float(df.loc[idx].iloc[0])
                if val is not None:
                    return val
            except (IndexError, KeyError, TypeError):
                continue
    return None


def _safe_dataframe(obj: Any) -> pd.DataFrame | None:
    if obj is None or not isinstance(obj, pd.DataFrame) or obj.empty:
        return None
    return obj


def _get_income_statement(ticker: yf.Ticker) -> pd.DataFrame | None:
    for attr in ("financials", "income_stmt", "quarterly_financials", "quarterly_income_stmt"):
        try:
            df = _safe_dataframe(getattr(ticker, attr, None))
            if df is not None:
                return df
        except Exception:
            continue
    return None


def _get_balance_sheet(ticker: yf.Ticker) -> pd.DataFrame | None:
    for attr in ("balance_sheet", "quarterly_balance_sheet"):
        try:
            df = _safe_dataframe(getattr(ticker, attr, None))
            if df is not None:
                return df
        except Exception:
            continue
    return None


def _fast_info_value(ticker: yf.Ticker, *keys: str) -> float | None:
    try:
        fi = ticker.fast_info
    except Exception:
        return None
    for key in keys:
        try:
            if hasattr(fi, key):
                val = getattr(fi, key)
            elif hasattr(fi, "__getitem__"):
                val = fi[key]
            else:
                continue
            fval = _to_float(val)
            if fval is not None and fval > 0:
                return fval
        except Exception:
            continue
    return None


def _last_close_price(ticker: yf.Ticker) -> float | None:
    try:
        hist = ticker.history(period="5d", auto_adjust=True)
        if hist is not None and not hist.empty:
            return _to_float(hist["Close"].iloc[-1])
    except Exception:
        pass
    try:
        data = yf.download(
            ticker.ticker,
            period="5d",
            progress=False,
            threads=False,
            auto_adjust=True,
        )
        if data is not None and not data.empty:
            close = data["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            return _to_float(close.iloc[-1])
    except Exception:
        pass
    return None


def _merge_ticker_info(ticker: yf.Ticker) -> dict:
    """Build a single info dict from every source yfinance exposes."""
    merged: dict = {}
    try:
        raw = ticker.info
        if isinstance(raw, dict) and raw:
            merged.update(raw)
    except Exception:
        pass

    fast_map = {
        "market_cap": "marketCap",
        "shares": "sharesOutstanding",
        "last_price": "currentPrice",
        "year_high": "fiftyTwoWeekHigh",
        "year_low": "fiftyTwoWeekLow",
    }
    try:
        fi = ticker.fast_info
        for src, dest in fast_map.items():
            if dest in merged and merged.get(dest) is not None:
                continue
            try:
                val = getattr(fi, src, None)
                if val is None and hasattr(fi, "__getitem__"):
                    val = fi[src]
                if val is not None:
                    merged[dest] = val
            except Exception:
                continue
    except Exception:
        pass
    return merged


def _resolve_market_cap(ticker: yf.Ticker, info: dict) -> float | None:
    for key in ("marketCap", "enterpriseValue"):
        cap = _to_float(info.get(key))
        if cap is not None and cap > 0:
            return cap

    cap = _fast_info_value(ticker, "market_cap", "marketCap")
    if cap is not None:
        return cap

    shares = _to_float(info.get("sharesOutstanding"))
    if shares is None:
        shares = _fast_info_value(ticker, "shares", "sharesOutstanding")

    price = _to_float(
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
    )
    if price is None:
        price = _fast_info_value(ticker, "last_price", "lastPrice", "regularMarketPrice")
    if price is None:
        price = _last_close_price(ticker)

    if shares is not None and price is not None and shares > 0 and price > 0:
        return shares * price

    return None


def _resolve_total_debt(ticker: yf.Ticker, info: dict) -> float:
    debt = _to_float(info.get("totalDebt"))
    if debt is not None:
        return debt
    bs = _get_balance_sheet(ticker)
    debt = _df_row_value(bs, "total debt")
    if debt is not None:
        return debt
    long_debt = _df_row_value(bs, "long term debt", "long-term debt") or 0.0
    short_debt = _df_row_value(bs, "current debt", "short long term debt") or 0.0
    return long_debt + short_debt


def _resolve_cash(ticker: yf.Ticker, info: dict) -> float:
    cash = _to_float(info.get("totalCash"))
    if cash is not None:
        return cash
    bs = _get_balance_sheet(ticker)
    cash = _df_row_value(
        bs,
        "cash and cash equivalents",
        "cash cash equivalents and short term investments",
        "cash financial",
    )
    return cash if cash is not None else 0.0


def _resolve_revenue(ticker: yf.Ticker, info: dict) -> float | None:
    revenue = _to_float(info.get("totalRevenue"))
    if revenue is not None and revenue > 0:
        return revenue
    inc = _get_income_statement(ticker)
    revenue = _df_row_value(inc, "total revenue", "total revenues", "revenue")
    return revenue


def _financials_value(financials: pd.DataFrame | None, keyword: str) -> float:
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


def _sum_non_halal_income(financials: pd.DataFrame | None) -> float:
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
    """
    Fetch stock data via yfinance with cloud-friendly fallbacks.
    Returns None on hard failure, or {"error": "..."} if market cap cannot be resolved.
    """
    try:
        symbol = symbol.strip().upper()
        if not symbol or not re.match(r"^[A-Z.\-]{1,10}$", symbol):
            return None

        ticker = yf.Ticker(symbol)
        info = _merge_ticker_info(ticker)
        income_df = _get_income_statement(ticker)

        company_name, sector, industry = _resolve_company_profile(
            ticker, info, symbol
        )

        market_cap = _resolve_market_cap(ticker, info)
        if market_cap is None or market_cap <= 0:
            return {"error": "Market cap unavailable"}

        total_debt = _resolve_total_debt(ticker, info)
        cash = _resolve_cash(ticker, info)
        total_revenue = _resolve_revenue(ticker, info)

        interest_income = _financials_value(income_df, "Interest")
        non_halal_income = _sum_non_halal_income(income_df)

        return {
            "symbol": symbol,
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "market_cap": market_cap,
            "total_debt": total_debt,
            "cash": cash,
            "total_revenue": total_revenue,
            "interest_income": interest_income,
            "non_halal_income": non_halal_income,
        }
    except Exception:
        return None