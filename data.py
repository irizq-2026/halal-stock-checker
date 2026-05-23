"""Data fetching layer for Halal Stock Checker."""

from __future__ import annotations

import os
import random
import re
import time
from typing import Any, Callable, TypeVar

import pandas as pd
import yfinance as yf

T = TypeVar("T")

_CACHE_DIR = os.environ.get("YFINANCE_CACHE_DIR", "/tmp/yfinance-cache")
os.makedirs(_CACHE_DIR, exist_ok=True)
try:
    yf.set_tz_cache_location(_CACHE_DIR)
except Exception:
    pass

NON_HALAL_KEYWORDS = ("insurance", "gambling", "alcohol", "tobacco")
EXCLUDE_LABEL_PATTERNS = ("minority interest", "noncontrolling interest")
UNKNOWN_PROFILE_VALUES = frozenset({"", "unknown", "n/a", "na", "none", "—", "-"})

# Retry tuning for Yahoo rate limits on Streamlit Cloud
MAX_RETRIES = 3
RETRY_DELAYS = (0.5, 1.0, 2.0)


class TransientDataError(Exception):
    """Temporary Yahoo/network failure — callers should not cache this result."""


def _clean_profile_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in UNKNOWN_PROFILE_VALUES:
        return ""
    return text


def _jitter_sleep(seconds: float) -> None:
    time.sleep(seconds + random.uniform(0.05, 0.35))


def _retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = MAX_RETRIES,
    delays: tuple[float, ...] = RETRY_DELAYS,
) -> T | None:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
        if attempt < attempts - 1:
            _jitter_sleep(delays[min(attempt, len(delays) - 1)])
    if last_error:
        return None
    return None


def _merge_profile_dicts(*parts: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for key in ("company_name", "sector", "industry"):
        for part in parts:
            val = _clean_profile_text(part.get(key))
            if val and not merged.get(key):
                merged[key] = val
    return merged


def _parse_quote_summary_block(block: dict) -> dict[str, str]:
    asset = block.get("assetProfile") or {}
    summary = block.get("summaryProfile") or {}
    price = block.get("price") or {}
    return {
        "company_name": _clean_profile_text(
            price.get("longName")
            or price.get("shortName")
            or summary.get("longName")
            or summary.get("name")
        ),
        "sector": _clean_profile_text(
            asset.get("sector") or asset.get("sectorDisp") or summary.get("sector")
        ),
        "industry": _clean_profile_text(
            asset.get("industry") or asset.get("industryDisp") or summary.get("industry")
        ),
    }


def _profile_from_chart(dat: Any, symbol: str) -> dict[str, str]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    payload = dat.get_raw_json(url, params={"interval": "1d", "range": "5d"})
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return {}
    meta = results[0].get("meta") or {}
    return {
        "company_name": _clean_profile_text(meta.get("longName") or meta.get("shortName")),
        "sector": "",
        "industry": "",
    }


def _profile_from_quote_summary(dat: Any, symbol: str) -> dict[str, str]:
    modules = "assetProfile,summaryProfile,price"
    for host in (
        "https://query2.finance.yahoo.com",
        "https://query1.finance.yahoo.com",
    ):
        url = f"{host}/v10/finance/quoteSummary/{symbol}"
        payload = dat.get_raw_json(url, params={"modules": modules})
        results = payload.get("quoteSummary", {}).get("result") or []
        if results:
            parsed = _parse_quote_summary_block(results[0])
            if parsed.get("company_name") or parsed.get("sector") or parsed.get("industry"):
                return parsed
    return {}


def _profile_from_v7_quote(dat: Any, symbol: str) -> dict[str, str]:
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    payload = dat.get_raw_json(url, params={"symbols": symbol})
    results = payload.get("quoteResponse", {}).get("result") or []
    if not results:
        return {}
    row = results[0]
    return {
        "company_name": _clean_profile_text(row.get("longName") or row.get("shortName")),
        "sector": _clean_profile_text(row.get("sector")),
        "industry": _clean_profile_text(row.get("industry")),
    }


def _profile_from_info(ticker: yf.Ticker) -> dict[str, str]:
    info = ticker.info or {}
    if not isinstance(info, dict):
        return {}
    return {
        "company_name": _clean_profile_text(
            info.get("longName") or info.get("shortName") or info.get("displayName")
        ),
        "sector": _clean_profile_text(info.get("sector") or info.get("sectorDisp")),
        "industry": _clean_profile_text(info.get("industry") or info.get("industryDisp")),
    }


def _fetch_company_profile_once(ticker: yf.Ticker, symbol: str) -> dict[str, str]:
    parts: list[dict[str, str]] = []
    dat = getattr(ticker, "_data", None)

    if dat is not None:
        for fetcher in (
            lambda: _profile_from_quote_summary(dat, symbol),
            lambda: _profile_from_chart(dat, symbol),
            lambda: _profile_from_v7_quote(dat, symbol),
        ):
            try:
                parts.append(fetcher())
                _jitter_sleep(0.15)
            except Exception:
                continue

    try:
        parts.append(_profile_from_info(ticker))
    except Exception:
        pass

    return _merge_profile_dicts(*parts)



def _fetch_company_profile(ticker: yf.Ticker, symbol: str) -> dict[str, str]:
    profile: dict[str, str] = {}
    for attempt in range(MAX_RETRIES):
        profile = _fetch_company_profile_once(ticker, symbol)
        if profile.get("company_name") or profile.get("sector") or profile.get("industry"):
            return profile
        if attempt < MAX_RETRIES - 1:
            _jitter_sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
    return profile


def _resolve_company_profile(
    ticker: yf.Ticker, info: dict, symbol: str
) -> tuple[str, str, str]:
    profile = _fetch_company_profile(ticker, symbol)

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


def _last_close_price(ticker: yf.Ticker, symbol: str) -> float | None:
    try:
        hist = ticker.history(period="5d", auto_adjust=True)
        if hist is not None and not hist.empty:
            return _to_float(hist["Close"].iloc[-1])
    except Exception:
        pass
    try:
        data = yf.download(
            symbol,
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
    }
    try:
        fi = ticker.fast_info
        for src, dest in fast_map.items():
            if merged.get(dest) is not None:
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


def _resolve_market_cap(ticker: yf.Ticker, info: dict, symbol: str) -> float | None:
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
        price = _last_close_price(ticker, symbol)

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
    return _df_row_value(inc, "total revenue", "total revenues", "revenue")


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


def _fetch_stock_data_once(symbol: str) -> dict:
    ticker = yf.Ticker(symbol)

    info = _merge_ticker_info(ticker)
    company_name, sector, industry = _resolve_company_profile(ticker, info, symbol)
    _jitter_sleep(0.15)

    market_cap = _resolve_market_cap(ticker, info, symbol)
    if market_cap is None or market_cap <= 0:
        raise TransientDataError("Market cap unavailable")

    income_df = _get_income_statement(ticker)

    return {
        "symbol": symbol,
        "company_name": company_name,
        "sector": sector,
        "industry": industry,
        "market_cap": market_cap,
        "total_debt": _resolve_total_debt(ticker, info),
        "cash": _resolve_cash(ticker, info),
        "total_revenue": _resolve_revenue(ticker, info),
        "interest_income": _financials_value(income_df, "Interest"),
        "non_halal_income": _sum_non_halal_income(income_df),
    }


def fetch_stock_data(symbol: str) -> dict | None:
    try:
        symbol = symbol.strip().upper()
        if not symbol or not re.match(r"^[A-Z.\-]{1,10}$", symbol):
            return None

        def _attempt() -> dict:
            return _fetch_stock_data_once(symbol)

        result = _retry_call(_attempt, attempts=MAX_RETRIES)
        if result:
            return result

        # Last try — may raise TransientDataError for UI message
        return _fetch_stock_data_once(symbol)
    except TransientDataError:
        raise
    except Exception:
        return None
