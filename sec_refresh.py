"""SEC ingestion pipeline and weekly refresh orchestration."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import aiohttp
import yfinance as yf
from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from config import settings
from db import session_scope
from models import Company, Filing, HalalScreenResult, NormalizedFinancial, RawFinancialFact
from rules import screen_stock

LOGGER = logging.getLogger(__name__)

SEC_TICKER_MAPPING_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"

FIELD_TOTAL_DEBT = "total_debt"
FIELD_TOTAL_CASH = "total_cash"
FIELD_ACCOUNTS_RECEIVABLE = "accounts_receivable"
FIELD_TOTAL_REVENUE = "total_revenue"
FIELD_INTEREST_INCOME = "interest_income"

INTEREST_PRIMARY_CONCEPT = "InvestmentIncomeInterest"
INTEREST_BUNDLED_CONCEPT = "InvestmentIncomeInterestAndDividend"
INTEREST_UPPER_BOUNDARY_CONCEPT = "NonoperatingIncomeExpense"
FINTECH_STABLECOIN_CONCEPTS = (
    "ReserveIncome",
    "ReserveFeeRevenue",
    "StablecoinReserveRevenue",
    "InterestOnSegregatedAssets",
    "InterestIncomeOperating",
    "InterestAndDividendIncomeOperating",
)
FINTECH_STABLECOIN_TERMS = tuple(
    term.lower()
    for term in (
        "Reserve Income",
        "Reserve Fee Revenue",
        "Stablecoin Reserve Revenue",
        "Interest on Segregated Assets",
        "Interest Income, Operating",
        "Interest And Dividend Income Operating",
    )
)

DEBT_CONCEPTS = (
    "LongTermDebt",
    "LongTermDebtCurrent",
    "ShortTermBorrowings",
    "CommercialPaper",
)
CASH_CONCEPTS = (
    "CashAndCashEquivalentsAtCarryingValue",
    "ShortTermInvestments",
    "MarketableSecuritiesCurrent",
)
ACCOUNTS_RECEIVABLE_CONCEPTS = (
    "AccountsReceivableNetCurrent",
    "ReceivablesNetCurrent",
)
SHORT_TERM_NOTES_PAY_CONCEPTS = (
    "NotesPayableCurrent",
    "DebtCurrent",
)
RESTRICTED_CASH_CONCEPTS = (
    "RestrictedCashAndCashEquivalentsAtCarryingValue",
    "RestrictedCashAndCashEquivalentsCurrent",
    "RestrictedCash",
)
LONG_TERM_SECURITIES_CONCEPTS = (
    "MarketableSecuritiesNoncurrent",
    "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent",
)
INTEREST_INCOME_CONCEPTS = (
    INTEREST_PRIMARY_CONCEPT,
    INTEREST_BUNDLED_CONCEPT,
    INTEREST_UPPER_BOUNDARY_CONCEPT,
    "InterestIncomeOperating",
    "InterestAndDividendIncomeOperating",
    "InterestAndFeeIncomeLoansAndLeases",
)
NON_OPERATING_INTEREST_CONCEPTS = (
    "InvestmentIncomeInterest",
    "InterestIncomeOperating",
    "InterestAndFeeIncomeLoansAndLeases",
)
DIVIDEND_INCOME_CONCEPTS = (
    "InvestmentIncomeDividend",
    "DividendIncome",
)
TOTAL_REVENUE_CONCEPTS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)

ALL_REQUIRED_CONCEPTS = tuple(
    dict.fromkeys(
        DEBT_CONCEPTS
        + CASH_CONCEPTS
        + ACCOUNTS_RECEIVABLE_CONCEPTS
        + SHORT_TERM_NOTES_PAY_CONCEPTS
        + RESTRICTED_CASH_CONCEPTS
        + LONG_TERM_SECURITIES_CONCEPTS
        + INTEREST_INCOME_CONCEPTS
        + FINTECH_STABLECOIN_CONCEPTS
        + DIVIDEND_INCOME_CONCEPTS
        + TOTAL_REVENUE_CONCEPTS
    )
)

LOG_DIR = Path("logs")
LOG_FILES = {
    "missing_xbrl": LOG_DIR / "missing_xbrl.log",
    "cik_not_found": LOG_DIR / "cik_not_found.log",
    "yfinance_errors": LOG_DIR / "yfinance_errors.log",
    "foreign_filer": LOG_DIR / "foreign_filer.log",
    "no_xbrl": LOG_DIR / "no_xbrl.log",
    "pipeline_errors": LOG_DIR / "pipeline_errors.log",
}

RAW_FACTS_VALUE_LIMIT = 10**18
RATIO_NUMERIC_LIMIT = 10**4
PLACEHOLDER_ACCESSION = "NO-DATA-PLACEHOLDER"
PLACEHOLDER_FILING_TYPE = "NO-DATA"
SUPPORTED_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}


def _normalize_cik(cik: str | int) -> str:
    return str(cik).strip().zfill(10)


def _parse_date(raw: Any) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), "%Y-%m-%d").date()
    except ValueError:
        return None


def _latest_supported_filing(submissions: dict[str, Any]) -> dict[str, Any] | None:
    recent = ((submissions.get("filings") or {}).get("recent") or {})
    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    filing_dates = recent.get("filingDate") or []
    total = min(len(forms), len(accessions), len(filing_dates))
    rows: list[dict[str, Any]] = []
    for idx in range(total):
        form = str(forms[idx] or "").upper().strip()
        if form not in SUPPORTED_FORMS:
            continue
        filing_date = _parse_date(filing_dates[idx])
        if filing_date is None:
            continue
        accession = str(accessions[idx] or "").strip()
        if not accession:
            continue
        rows.append(
            {
                "filing_type": form,
                "accession_number": accession,
                "filing_date": filing_date,
            }
        )
    if not rows:
        return None
    rows.sort(key=lambda row: row["filing_date"], reverse=True)
    return rows[0]


def _to_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    return value


@dataclass
class RefreshSummary:
    ticker: str
    processed_filings: int
    skipped_filings: int
    status: str
    message: str = ""


@dataclass
class ConceptPoint:
    concept: str
    value: float
    end: date
    filed: date | None
    form: str
    accession_number: str
    frame: str | None
    unit: str


@dataclass
class MetricSelection:
    value: float | None
    period_end: date | None
    points: list[ConceptPoint]
    method: str
    concept: str | None


@dataclass
class TickerEdgarPacket:
    ticker: str
    cik: str | None
    company_name: str
    total_debt: float | None
    total_cash: float | None
    accounts_receivable: float | None
    total_revenue: float | None
    interest_income: float | None
    interest_income_source: str | None
    interest_income_method: str
    interest_income_fallback_step: str | None
    interest_income_disclaimer: str | None
    interest_income_calculation_details: list[dict[str, Any]]
    balance_sheet_date: date | None
    income_statement_date: date | None
    primary_filing_type: str
    primary_accession_number: str
    primary_filing_date: date
    points: list[ConceptPoint]
    missing_fields: list[str]
    placeholder_reason: str | None
    has_10k: bool
    has_20f: bool
    sic_code: str | None
    sic_description: str | None
    component_breakdown: dict[str, Any]


@dataclass
class YFinanceSnapshot:
    market_cap: float | None
    sector: str | None
    industry: str | None
    shares_outstanding: float | None
    latest_closing_price: float | None


@dataclass
class RunAudit:
    start_ts: float = field(default_factory=time.monotonic)
    missing_xbrl: set[str] = field(default_factory=set)
    cik_not_found: set[str] = field(default_factory=set)
    yfinance_errors: set[str] = field(default_factory=set)
    foreign_filer: set[str] = field(default_factory=set)
    no_xbrl: set[str] = field(default_factory=set)
    pipeline_errors: set[str] = field(default_factory=set)

    def record_missing_xbrl(self, ticker: str, field_name: str) -> None:
        self.missing_xbrl.add(f"{ticker}|{field_name}")

    def record_cik_not_found(self, ticker: str) -> None:
        self.cik_not_found.add(ticker)

    def record_yfinance_error(self, ticker: str, message: str) -> None:
        self.yfinance_errors.add(f"{ticker}|{message}")

    def record_foreign_filer(self, ticker: str, message: str) -> None:
        self.foreign_filer.add(f"{ticker}|{message}")

    def record_no_xbrl(self, ticker: str, message: str) -> None:
        self.no_xbrl.add(f"{ticker}|{message}")

    def record_pipeline_error(self, ticker: str, message: str) -> None:
        self.pipeline_errors.add(f"{ticker}|{message}")

    def runtime_seconds(self) -> int:
        return int(time.monotonic() - self.start_ts)

    def flush_logs(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        mapping = {
            "missing_xbrl": self.missing_xbrl,
            "cik_not_found": self.cik_not_found,
            "yfinance_errors": self.yfinance_errors,
            "foreign_filer": self.foreign_filer,
            "no_xbrl": self.no_xbrl,
            "pipeline_errors": self.pipeline_errors,
        }
        for key, values in mapping.items():
            path = LOG_FILES[key]
            if values:
                body = "\n".join(sorted(values)) + "\n"
            else:
                body = ""
            path.write_text(body, encoding="utf-8")


def _unique_ticker_count(entries: set[str]) -> int:
    tickers = {entry.split("|", 1)[0].strip().upper() for entry in entries if entry}
    return len(tickers)


class AsyncRateLimiter:
    """Token interval limiter with asyncio primitives."""

    def __init__(self, requests_per_second: float) -> None:
        rps = max(min(requests_per_second, 10.0), 0.1)
        self._interval = 1.0 / rps
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                await asyncio.sleep(self._next_allowed - now)
                now = time.monotonic()
            self._next_allowed = now + self._interval


class AsyncEdgarClient:
    """Async EDGAR client with SEC-compliant rate limiting."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(10)
        self._rate_limiter = AsyncRateLimiter(10.0)
        self._headers = {
            "User-Agent": settings.sec_user_agent,
            "Accept-Encoding": "gzip, deflate",
        }

    async def __aenter__(self) -> "AsyncEdgarClient":
        timeout = aiohttp.ClientTimeout(total=settings.sec_timeout_seconds)
        self._session = aiohttp.ClientSession(timeout=timeout, headers=self._headers)
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _request_json(self, url: str) -> tuple[int, dict[str, Any] | None]:
        if self._session is None:
            raise RuntimeError("AsyncEdgarClient session not initialized.")

        delay = 0.5
        last_exc: Exception | None = None
        for attempt in range(settings.sec_max_retries):
            try:
                await self._rate_limiter.wait()
                async with self._semaphore:
                    async with self._session.get(url) as response:
                        status = response.status
                        if status == 404:
                            return status, None
                        if status == 429:
                            await asyncio.sleep(max(delay, 1.0))
                            delay = min(delay * 2, 10.0)
                            continue
                        if status >= 500:
                            await asyncio.sleep(delay)
                            delay = min(delay * 2, 10.0)
                            continue
                        response.raise_for_status()
                        payload = await response.json(content_type=None)
                        if isinstance(payload, dict):
                            return status, payload
                        return status, None
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                if attempt < settings.sec_max_retries - 1:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 10.0)
                    continue
        if last_exc:
            raise last_exc
        return 0, None

    async def fetch_ticker_mapping(self) -> dict[str, dict[str, str]]:
        _, payload = await self._request_json(SEC_TICKER_MAPPING_URL)
        mapping: dict[str, dict[str, str]] = {}
        if not payload:
            return mapping
        for _, row in payload.items():
            ticker = str((row or {}).get("ticker") or "").upper().strip()
            if not ticker:
                continue
            cik = _normalize_cik((row or {}).get("cik_str") or "")
            if not cik:
                continue
            mapping[ticker] = {
                "cik": cik,
                "company_name": str((row or {}).get("title") or ticker).strip() or ticker,
            }
        return mapping

    async def fetch_submissions(self, cik: str) -> dict[str, Any] | None:
        _, payload = await self._request_json(SEC_SUBMISSIONS_URL.format(cik=_normalize_cik(cik)))
        return payload

    async def fetch_company_concept(self, cik: str, concept: str) -> tuple[int, dict[str, Any] | None]:
        return await self._request_json(
            SEC_COMPANY_CONCEPT_URL.format(cik=_normalize_cik(cik), concept=concept),
        )


def _dedupe_quarter_rows(rows: list[ConceptPoint]) -> list[ConceptPoint]:
    best_by_end: dict[date, ConceptPoint] = {}
    for row in rows:
        previous = best_by_end.get(row.end)
        if previous is None:
            best_by_end[row.end] = row
            continue
        prev_filed = previous.filed or date.min
        curr_filed = row.filed or date.min
        if curr_filed >= prev_filed:
            best_by_end[row.end] = row
    ordered = list(best_by_end.values())
    ordered.sort(key=lambda item: item.end, reverse=True)
    return ordered


def _parse_concept_points(payload: dict[str, Any] | None, concept: str) -> list[ConceptPoint]:
    if not payload:
        return []
    units = payload.get("units") or {}
    points: list[ConceptPoint] = []
    for unit_name, entries in units.items():
        if unit_name != "USD" or not isinstance(entries, list):
            continue
        for raw in entries:
            end_date = _parse_date((raw or {}).get("end"))
            value = _to_float((raw or {}).get("val"))
            if end_date is None or value is None:
                continue
            points.append(
                ConceptPoint(
                    concept=concept,
                    value=value,
                    end=end_date,
                    filed=_parse_date((raw or {}).get("filed")),
                    form=str((raw or {}).get("form") or "").upper().strip(),
                    accession_number=str((raw or {}).get("accn") or "").strip(),
                    frame=str((raw or {}).get("frame") or "").strip() or None,
                    unit=unit_name,
                )
            )
    return points


def _latest_10k(rows: list[ConceptPoint]) -> ConceptPoint | None:
    ten_k = [row for row in rows if row.form == "10-K"]
    if not ten_k:
        return None
    ten_k.sort(
        key=lambda row: (
            row.end,
            row.filed or date.min,
        ),
        reverse=True,
    )
    return ten_k[0]


def _income_ttm_or_10k(rows: list[ConceptPoint]) -> MetricSelection:
    quarters = _dedupe_quarter_rows([row for row in rows if row.form == "10-Q"])
    if len(quarters) >= 4:
        selected = quarters[:4]
        value = sum(row.value for row in selected)
        return MetricSelection(
            value=value,
            period_end=selected[0].end,
            points=selected,
            method="ttm_10q",
            concept=selected[0].concept,
        )

    annual = _latest_10k(rows)
    if annual is not None:
        return MetricSelection(
            value=annual.value,
            period_end=annual.end,
            points=[annual],
            method="latest_10k_fallback",
            concept=annual.concept,
        )
    return MetricSelection(
        value=None,
        period_end=None,
        points=[],
        method="missing",
        concept=None,
    )


def _select_first_balance(rows_by_concept: dict[str, list[ConceptPoint]], concepts: tuple[str, ...]) -> MetricSelection:
    for concept in concepts:
        point = _latest_10k(rows_by_concept.get(concept) or [])
        if point is not None:
            return MetricSelection(
                value=point.value,
                period_end=point.end,
                points=[point],
                method="latest_10k_first_match",
                concept=concept,
            )
    return MetricSelection(
        value=None,
        period_end=None,
        points=[],
        method="missing",
        concept=None,
    )


def _select_sum_balance(rows_by_concept: dict[str, list[ConceptPoint]], concepts: tuple[str, ...]) -> MetricSelection:
    selected_points: list[ConceptPoint] = []
    for concept in concepts:
        point = _latest_10k(rows_by_concept.get(concept) or [])
        if point is not None:
            selected_points.append(point)

    if not selected_points:
        return MetricSelection(
            value=None,
            period_end=None,
            points=[],
            method="missing",
            concept=None,
        )

    period_end = max(point.end for point in selected_points)
    return MetricSelection(
        value=sum(point.value for point in selected_points),
        period_end=period_end,
        points=selected_points,
        method="sum_latest_10k",
        concept=None,
    )


def _select_first_income(rows_by_concept: dict[str, list[ConceptPoint]], concepts: tuple[str, ...]) -> MetricSelection:
    for concept in concepts:
        selection = _income_ttm_or_10k(rows_by_concept.get(concept) or [])
        if selection.value is not None:
            selection.concept = concept
            return selection
    return MetricSelection(
        value=None,
        period_end=None,
        points=[],
        method="missing",
        concept=None,
    )


def _is_non_zero(value: float | None) -> bool:
    return value is not None and value != 0.0


def _quarter_label(period_end: date) -> str:
    quarter = ((period_end.month - 1) // 3) + 1
    return f"Q{quarter} {period_end.year}"


def _log_ratio3_source(ticker: str, point: ConceptPoint, source_tag: str) -> None:
    message = f"[Ratio3Source] {_quarter_label(point.end)} {ticker.upper()} → {source_tag}"
    LOGGER.info(message)
    print(message)


def _matches_fintech_stablecoin_term(concept_name: str) -> bool:
    if concept_name in FINTECH_STABLECOIN_CONCEPTS:
        return True
    normalized = (concept_name or "").replace("_", " ").replace("-", " ").lower()
    return any(term in normalized for term in FINTECH_STABLECOIN_TERMS)


def _select_interest_income_with_fallback(
    rows_by_concept: dict[str, list[ConceptPoint]],
    ticker: str,
) -> tuple[dict[str, Any], str | None, str | None]:
    primary_rows = rows_by_concept.get(INTEREST_PRIMARY_CONCEPT) or []
    bundled_rows = rows_by_concept.get(INTEREST_BUNDLED_CONCEPT) or []
    upper_rows = rows_by_concept.get(INTEREST_UPPER_BOUNDARY_CONCEPT) or []
    total_impermissible_income: float | None = None
    calculation_details: list[dict[str, Any]] = []
    captured_amounts: set[float] = set()
    selected = MetricSelection(
        value=None,
        period_end=None,
        points=[],
        method="missing",
        concept=None,
    )
    fallback_step: str | None = None
    fallback_disclaimer: str | None = None

    primary_selection = _income_ttm_or_10k(primary_rows)
    if _is_non_zero(primary_selection.value):
        primary_selection.concept = INTEREST_PRIMARY_CONCEPT
        for point in primary_selection.points:
            _log_ratio3_source(ticker, point, INTEREST_PRIMARY_CONCEPT)
        selected = primary_selection
        total_impermissible_income = primary_selection.value
        captured_amounts.add(round(float(primary_selection.value), 6))
        calculation_details.append(
            {
                "lineName": "Traditional Interest Income",
                "amount": float(primary_selection.value),
                "sourceSection": "Non-Operating",
            }
        )

    if selected.value is None:
        bundled_candidates = (
            INTEREST_BUNDLED_CONCEPT,
            "InterestAndDividendIncomeOperating",
            "InterestIncomeOperating",
        )
        for bundled_concept in bundled_candidates:
            bundled_selection = _income_ttm_or_10k(rows_by_concept.get(bundled_concept) or [])
            if not _is_non_zero(bundled_selection.value):
                continue
            bundled_selection.concept = bundled_concept
            for point in bundled_selection.points:
                _log_ratio3_source(ticker, point, bundled_concept)
            selected = bundled_selection
            fallback_step = "step2"
            fallback_disclaimer = (
                "⚠️ Interest & dividend income reported as a combined figure. "
                "This ratio may be slightly overstated if dividend income is included."
            )
            total_impermissible_income = bundled_selection.value
            captured_amounts.add(round(float(bundled_selection.value), 6))
            detail_line_name = "Interest Income, Operating (Bundled)"
            if bundled_concept == "InterestAndDividendIncomeOperating":
                detail_line_name = "Stablecoin Reserve Income"
            elif bundled_concept == "InterestIncomeOperating":
                detail_line_name = "Interest Income, Operating"
            calculation_details.append(
                {
                    "lineName": detail_line_name,
                    "amount": float(bundled_selection.value),
                    "sourceSection": "Revenue/Operating Income",
                }
            )
            break

    if selected.value is None:
        upper_selection = _income_ttm_or_10k(upper_rows)
        if upper_selection.value is not None:
            upper_selection.concept = INTEREST_UPPER_BOUNDARY_CONCEPT
            for point in upper_selection.points:
                _log_ratio3_source(ticker, point, INTEREST_UPPER_BOUNDARY_CONCEPT)
            selected = upper_selection
            fallback_step = "step3"
            fallback_disclaimer = (
                "⚠️ Interest income not separately reported for this period. "
                "Non-operating income used as the upper boundary. "
                "Ratio 3 reflects a conservative ceiling, not an exact figure."
            )
            total_impermissible_income = upper_selection.value
            if upper_selection.value is not None:
                captured_amounts.add(round(float(upper_selection.value), 6))
                upper_line_name = "Apple-Other Income Fallback" if ticker.upper() == "AAPL" else "Non-Operating Income Fallback"
                upper_source_section = "Apple-Other Income" if ticker.upper() == "AAPL" else "Non-Operating"
                calculation_details.append(
                    {
                        "lineName": upper_line_name,
                        "amount": float(upper_selection.value),
                        "sourceSection": upper_source_section,
                    }
                )

    # ── FINTECH/STABLECOIN FALLBACK (added for CRCL-type companies) ──
    # ── Do NOT merge with or modify the blocks above ──────────────────
    for concept_name, concept_rows in rows_by_concept.items():
        if not _matches_fintech_stablecoin_term(concept_name):
            continue
        fintech_selection = _income_ttm_or_10k(concept_rows or [])
        fintech_value = fintech_selection.value
        if not _is_non_zero(fintech_value):
            continue
        rounded_value = round(float(fintech_value), 6)
        if rounded_value in captured_amounts:
            continue
        if total_impermissible_income is None:
            total_impermissible_income = 0.0
        total_impermissible_income += float(fintech_value)
        captured_amounts.add(rounded_value)
        calculation_details.append(
            {
                "lineName": concept_name,
                "amount": float(fintech_value),
                "sourceSection": "Revenue/Operating Income",
            }
        )
        for point in fintech_selection.points:
            _log_ratio3_source(ticker, point, concept_name)
        if selected.value is None:
            selected = MetricSelection(
                value=float(fintech_value),
                period_end=fintech_selection.period_end,
                points=fintech_selection.points,
                method="fintech_stablecoin_fallback",
                concept=concept_name,
            )

    if total_impermissible_income is not None:
        selected = MetricSelection(
            value=float(total_impermissible_income),
            period_end=selected.period_end,
            points=selected.points,
            method=selected.method,
            concept=selected.concept,
        )

    return (
        {
            "totalImpermissibleIncome": total_impermissible_income,
            "calculationDetails": calculation_details,
            "selection": selected,
        },
        fallback_step,
        fallback_disclaimer,
    )


def _points_to_raw_rows(points: list[ConceptPoint]) -> list[dict[str, Any]]:
    seen: set[tuple[str, date, str, str]] = set()
    rows: list[dict[str, Any]] = []
    for point in points:
        if abs(point.value) >= RAW_FACTS_VALUE_LIMIT:
            continue
        key = (point.concept, point.end, point.form, point.accession_number)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "taxonomy": "us-gaap",
                "tag": point.concept,
                "unit": point.unit,
                "value": point.value,
                "period_start": None,
                "period_end": point.end,
                "filed_date": point.filed,
                "frame": point.frame,
                "raw_json": {
                    "taxonomy": "us-gaap",
                    "tag": point.concept,
                    "unit": point.unit,
                    "value": point.value,
                    "period_end": point.end.isoformat(),
                    "filed_date": point.filed.isoformat() if point.filed else None,
                    "form": point.form,
                    "accession_number": point.accession_number,
                    "frame": point.frame,
                },
            }
        )
    return rows


def _sum_optional(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)


def _build_component_breakdown(
    *,
    total_debt: float | None,
    total_cash: float | None,
    total_revenue: float | None,
    interest_income: float | None,
    commercial_paper: float | None,
    short_term_notes_pay: float | None,
    current_long_term_debt: float | None,
    noncurrent_debt_obligations: float | None,
    bank_cash: float | None,
    restricted_cash_reserves: float | None,
    short_term_securities: float | None,
    long_term_bonds_paper: float | None,
    non_operating_cash_interest: float | None,
    equity_investment_dividends: float | None,
) -> dict[str, Any]:
    short_term_borrowings = _sum_optional(commercial_paper, short_term_notes_pay)
    long_term_borrowings = _sum_optional(current_long_term_debt, noncurrent_debt_obligations)
    cash_and_equivalents = _sum_optional(bank_cash, restricted_cash_reserves)
    marketable_debt_securities = _sum_optional(short_term_securities, long_term_bonds_paper)
    passive_financial_yield = _sum_optional(non_operating_cash_interest, equity_investment_dividends)
    total_annual_prohibited_revenue = interest_income

    return {
        "valuation": {
            "baseline_label": "Market Cap Baseline",
            "shares_outstanding": None,
            "latest_closing_price": None,
        },
        "debt": {
            "total_borrowed_capital": total_debt,
            "short_term_borrowings": short_term_borrowings,
            "commercial_paper": commercial_paper,
            "short_term_notes_pay": short_term_notes_pay,
            "long_term_borrowings": long_term_borrowings,
            "current_long_term_debt": current_long_term_debt,
            "noncurrent_debt_obligations": noncurrent_debt_obligations,
        },
        "liquid_assets": {
            "total_interest_earning_pools": total_cash,
            "cash_and_cash_equivalents": cash_and_equivalents,
            "bank_cash": bank_cash,
            "restricted_cash_reserves": restricted_cash_reserves,
            "marketable_debt_securities": marketable_debt_securities,
            "short_term_securities": short_term_securities,
            "long_term_bonds_paper": long_term_bonds_paper,
        },
        "purging": {
            "total_annual_prohibited_revenue": total_annual_prohibited_revenue,
            "core_prohibited_operations": None,
            "passive_financial_yield": passive_financial_yield,
            "non_operating_cash_interest": non_operating_cash_interest,
            "equity_investment_dividends": equity_investment_dividends,
            "total_revenue_baseline": total_revenue,
        },
    }


def _is_core_interest_profile(sector: str | None, industry: str | None) -> bool:
    profile = f"{sector or ''} {industry or ''}".lower()
    keywords = ("bank", "banking", "insurance", "insurer", "reinsurance")
    return any(keyword in profile for keyword in keywords)


async def _fetch_ticker_packet(
    client: AsyncEdgarClient,
    mapping: dict[str, dict[str, str]],
    ticker: str,
    audit: RunAudit,
) -> TickerEdgarPacket:
    symbol = ticker.upper().strip()
    mapped = mapping.get(symbol)
    if mapped is None:
        audit.record_cik_not_found(symbol)
        today = datetime.now(UTC).date()
        return TickerEdgarPacket(
            ticker=symbol,
            cik=None,
            company_name=symbol,
            total_debt=None,
            total_cash=None,
            accounts_receivable=None,
            total_revenue=None,
            interest_income=None,
            interest_income_source=None,
            interest_income_method="missing",
            interest_income_fallback_step=None,
            interest_income_disclaimer=None,
            interest_income_calculation_details=[],
            balance_sheet_date=None,
            income_statement_date=None,
            primary_filing_type=PLACEHOLDER_FILING_TYPE,
            primary_accession_number=PLACEHOLDER_ACCESSION,
            primary_filing_date=today,
            points=[],
            missing_fields=[
                FIELD_TOTAL_DEBT,
                FIELD_TOTAL_CASH,
                FIELD_ACCOUNTS_RECEIVABLE,
                FIELD_TOTAL_REVENUE,
                FIELD_INTEREST_INCOME,
            ],
            placeholder_reason="CIK not found in SEC ticker map.",
            has_10k=False,
            has_20f=False,
            sic_code=None,
            sic_description=None,
            component_breakdown=_build_component_breakdown(
                total_debt=None,
                total_cash=None,
                total_revenue=None,
                interest_income=None,
                commercial_paper=None,
                short_term_notes_pay=None,
                current_long_term_debt=None,
                noncurrent_debt_obligations=None,
                bank_cash=None,
                restricted_cash_reserves=None,
                short_term_securities=None,
                long_term_bonds_paper=None,
                non_operating_cash_interest=None,
                equity_investment_dividends=None,
            ),
        )

    cik = mapped["cik"]
    submissions = await client.fetch_submissions(cik) or {}
    company_name = str(submissions.get("name") or mapped["company_name"]).strip() or symbol
    sic_code = str(submissions.get("sic") or "").strip() or None
    sic_description = str(submissions.get("sicDescription") or "").strip() or None
    latest_filing = _latest_supported_filing(submissions)

    recent_forms_raw = (((submissions.get("filings") or {}).get("recent") or {}).get("form") or [])
    recent_forms = {str(form or "").upper().strip() for form in recent_forms_raw if form}
    has_10k = "10-K" in recent_forms
    has_20f = "20-F" in recent_forms

    concept_tasks = {
        concept: asyncio.create_task(client.fetch_company_concept(cik, concept))
        for concept in ALL_REQUIRED_CONCEPTS
    }
    rows_by_concept: dict[str, list[ConceptPoint]] = {}
    for concept, task in concept_tasks.items():
        status, payload = await task
        if status == 404:
            rows_by_concept[concept] = []
            continue
        rows_by_concept[concept] = _parse_concept_points(payload, concept)

    debt_selection = _select_sum_balance(rows_by_concept, DEBT_CONCEPTS)
    cash_selection = _select_sum_balance(rows_by_concept, CASH_CONCEPTS)
    ar_selection = _select_first_balance(rows_by_concept, ACCOUNTS_RECEIVABLE_CONCEPTS)
    revenue_selection = _select_first_income(rows_by_concept, TOTAL_REVENUE_CONCEPTS)
    interest_result, interest_fallback_step, interest_disclaimer = _select_interest_income_with_fallback(
        rows_by_concept,
        symbol,
    )
    interest_total = _to_float(interest_result.get("totalImpermissibleIncome"))
    interest_selection = interest_result.get("selection")
    if not isinstance(interest_selection, MetricSelection):
        interest_selection = MetricSelection(
            value=None,
            period_end=None,
            points=[],
            method="missing",
            concept=None,
        )
    elif interest_total is not None:
        interest_selection = MetricSelection(
            value=interest_total,
            period_end=interest_selection.period_end,
            points=interest_selection.points,
            method=interest_selection.method,
            concept=interest_selection.concept,
        )
    interest_calculation_details = interest_result.get("calculationDetails")
    if not isinstance(interest_calculation_details, list):
        interest_calculation_details = []
    non_operating_interest_selection = _select_first_income(rows_by_concept, NON_OPERATING_INTEREST_CONCEPTS)
    dividend_selection = _select_first_income(rows_by_concept, DIVIDEND_INCOME_CONCEPTS)

    commercial_paper_selection = _select_first_balance(rows_by_concept, ("CommercialPaper",))
    short_term_notes_selection = _select_first_balance(
        rows_by_concept,
        ("ShortTermBorrowings",) + SHORT_TERM_NOTES_PAY_CONCEPTS,
    )
    current_long_term_debt_selection = _select_first_balance(rows_by_concept, ("LongTermDebtCurrent",))
    noncurrent_debt_selection = _select_first_balance(rows_by_concept, ("LongTermDebt",))
    bank_cash_selection = _select_first_balance(rows_by_concept, ("CashAndCashEquivalentsAtCarryingValue",))
    restricted_cash_selection = _select_sum_balance(rows_by_concept, RESTRICTED_CASH_CONCEPTS)
    short_term_securities_selection = _select_sum_balance(
        rows_by_concept,
        ("ShortTermInvestments", "MarketableSecuritiesCurrent"),
    )
    long_term_bonds_selection = _select_sum_balance(rows_by_concept, LONG_TERM_SECURITIES_CONCEPTS)

    selected_points = (
        debt_selection.points
        + cash_selection.points
        + ar_selection.points
        + revenue_selection.points
        + interest_selection.points
        + non_operating_interest_selection.points
        + dividend_selection.points
        + commercial_paper_selection.points
        + short_term_notes_selection.points
        + current_long_term_debt_selection.points
        + noncurrent_debt_selection.points
        + bank_cash_selection.points
        + restricted_cash_selection.points
        + short_term_securities_selection.points
        + long_term_bonds_selection.points
    )

    missing_fields: list[str] = []
    field_values = {
        FIELD_TOTAL_DEBT: debt_selection.value,
        FIELD_TOTAL_CASH: cash_selection.value,
        FIELD_ACCOUNTS_RECEIVABLE: ar_selection.value,
        FIELD_TOTAL_REVENUE: revenue_selection.value,
        FIELD_INTEREST_INCOME: interest_selection.value,
    }
    for field_name, value in field_values.items():
        if value is None:
            missing_fields.append(field_name)
            audit.record_missing_xbrl(symbol, field_name)

    all_missing = len(missing_fields) == len(field_values)
    placeholder_reason: str | None = None
    if not has_10k and has_20f:
        placeholder_reason = "Foreign filer (20-F) without recent 10-K coverage."
        audit.record_foreign_filer(symbol, placeholder_reason)
    elif all_missing:
        placeholder_reason = "No recent SEC 10-Q/10-K or company-facts concept data."
        audit.record_no_xbrl(symbol, placeholder_reason)

    balance_sheet_date = max(
        [dt for dt in (debt_selection.period_end, cash_selection.period_end, ar_selection.period_end) if dt],
        default=None,
    )
    income_statement_date = max(
        [dt for dt in (revenue_selection.period_end, interest_selection.period_end) if dt],
        default=None,
    )

    primary_date = (
        latest_filing["filing_date"]
        if latest_filing is not None
        else max(
            [dt for dt in (balance_sheet_date, income_statement_date) if dt],
            default=datetime.now(UTC).date(),
        )
    )
    primary_point = max(
        selected_points,
        key=lambda point: (
            point.end,
            point.filed or date.min,
        ),
        default=None,
    )
    primary_accession = (
        str(latest_filing.get("accession_number"))
        if latest_filing is not None and latest_filing.get("accession_number")
        else (
            primary_point.accession_number
            if primary_point and primary_point.accession_number
            else f"EDGAR-XBRL-{primary_date.isoformat()}"
        )
    )
    primary_form = (
        str(latest_filing.get("filing_type"))
        if latest_filing is not None and latest_filing.get("filing_type")
        else (primary_point.form if primary_point and primary_point.form else "10-K")
    )

    return TickerEdgarPacket(
        ticker=symbol,
        cik=cik,
        company_name=company_name,
        total_debt=debt_selection.value,
        total_cash=cash_selection.value,
        accounts_receivable=ar_selection.value,
        total_revenue=revenue_selection.value,
        interest_income=interest_selection.value,
        interest_income_source=interest_selection.concept,
        interest_income_method=interest_selection.method,
        interest_income_fallback_step=interest_fallback_step,
        interest_income_disclaimer=interest_disclaimer,
        interest_income_calculation_details=interest_calculation_details,
        balance_sheet_date=balance_sheet_date,
        income_statement_date=income_statement_date,
        primary_filing_type=primary_form,
        primary_accession_number=primary_accession,
        primary_filing_date=primary_date,
        points=selected_points,
        missing_fields=missing_fields,
        placeholder_reason=placeholder_reason,
        has_10k=has_10k,
        has_20f=has_20f,
        sic_code=sic_code,
        sic_description=sic_description,
        component_breakdown=_build_component_breakdown(
            total_debt=debt_selection.value,
            total_cash=cash_selection.value,
            total_revenue=revenue_selection.value,
            interest_income=interest_selection.value,
            commercial_paper=commercial_paper_selection.value,
            short_term_notes_pay=short_term_notes_selection.value,
            current_long_term_debt=current_long_term_debt_selection.value,
            noncurrent_debt_obligations=noncurrent_debt_selection.value,
            bank_cash=bank_cash_selection.value,
            restricted_cash_reserves=restricted_cash_selection.value,
            short_term_securities=short_term_securities_selection.value,
            long_term_bonds_paper=long_term_bonds_selection.value,
            non_operating_cash_interest=non_operating_interest_selection.value,
            equity_investment_dividends=dividend_selection.value,
        ),
    )


class SecRefreshService:
    """Handles SEC EDGAR XBRL -> yfinance -> Postgres refresh operations."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _ensure_company(self, packet: TickerEdgarPacket) -> Company:
        company = self.session.scalar(
            select(Company).where(Company.ticker == packet.ticker),
        )
        if company is None:
            company = Company(
                ticker=packet.ticker,
                cik=packet.cik or "0000000000",
                company_name=packet.company_name or packet.ticker,
            )
            self.session.add(company)
            self.session.flush()
            return company

        if packet.cik:
            company.cik = packet.cik
        if packet.company_name:
            company.company_name = packet.company_name
        return company

    def _upsert_filing(self, company_id: int, row: dict[str, Any]) -> Filing:
        filing = self.session.scalar(
            select(Filing).where(
                Filing.company_id == company_id,
                Filing.accession_number == row["accession_number"],
            )
        )
        if filing is None:
            filing = Filing(
                company_id=company_id,
                accession_number=row["accession_number"],
                filing_type=row["filing_type"],
                filing_date=row["filing_date"],
                fiscal_year=row.get("fiscal_year"),
                fiscal_period=row.get("fiscal_period"),
            )
            self.session.add(filing)
            self.session.flush()
            return filing

        filing.filing_type = row["filing_type"]
        filing.filing_date = row["filing_date"]
        filing.fiscal_year = row.get("fiscal_year")
        filing.fiscal_period = row.get("fiscal_period")
        self.session.flush()
        return filing

    def _store_raw_facts(self, company_id: int, filing_id: int, raw_rows: list[dict[str, Any]]) -> None:
        self.session.execute(
            delete(RawFinancialFact).where(
                RawFinancialFact.company_id == company_id,
                RawFinancialFact.filing_id == filing_id,
            )
        )
        if not raw_rows:
            return
        self.session.bulk_insert_mappings(
            RawFinancialFact,
            [
                {
                    "company_id": company_id,
                    "filing_id": filing_id,
                    **row,
                }
                for row in raw_rows
            ],
        )

    def _upsert_normalized(
        self,
        company_id: int,
        filing_id: int,
        packet: TickerEdgarPacket,
        yfinance_data: YFinanceSnapshot,
        sector: str | None,
        industry: str | None,
    ) -> NormalizedFinancial:
        row = self.session.scalar(
            select(NormalizedFinancial).where(
                NormalizedFinancial.company_id == company_id,
                NormalizedFinancial.filing_id == filing_id,
            )
        )
        if row is None:
            row = NormalizedFinancial(company_id=company_id, filing_id=filing_id)
            self.session.add(row)

        row.total_revenue = packet.total_revenue
        row.interest_income = packet.interest_income
        row.total_debt = packet.total_debt
        row.cash_and_equivalents = packet.total_cash
        row.total_assets = None
        row.market_cap = yfinance_data.market_cap
        row.operating_income = None
        row.net_income = None
        row.shares_outstanding = yfinance_data.shares_outstanding

        components = dict(packet.component_breakdown or {})
        valuation = dict(components.get("valuation") or {})
        valuation["shares_outstanding"] = yfinance_data.shares_outstanding
        valuation["latest_closing_price"] = yfinance_data.latest_closing_price
        valuation["baseline_label"] = "Market Cap Baseline" if yfinance_data.market_cap is not None else "Total Assets Baseline"
        components["valuation"] = valuation

        purging = dict(components.get("purging") or {})
        if packet.interest_income_calculation_details:
            purging["calculation_details"] = packet.interest_income_calculation_details
        core_prohibited = packet.total_revenue if _is_core_interest_profile(sector, industry) else 0.0
        purging["core_prohibited_operations"] = core_prohibited
        passive_yield = _to_float(purging.get("passive_financial_yield"))
        # When Ratio 3 uses fallback tags, preserve the resolved numerator in the
        # purging breakdown so the UI detail rows match the card-level value.
        if (
            not _is_core_interest_profile(sector, industry)
            and packet.interest_income is not None
            and packet.interest_income_fallback_step in {"step2", "step3"}
            and (passive_yield is None or passive_yield == 0.0)
        ):
            purging["passive_financial_yield"] = packet.interest_income
            passive_yield = packet.interest_income

        if _is_core_interest_profile(sector, industry):
            total_annual = packet.total_revenue
        elif packet.interest_income is not None:
            total_annual = packet.interest_income
        else:
            total_annual = _sum_optional(core_prohibited, passive_yield)
        purging["total_annual_prohibited_revenue"] = total_annual
        components["purging"] = purging

        row.source_metadata_json = {
            "data_source": "edgar_xbrl",
            "balance_sheet_date": packet.balance_sheet_date.isoformat() if packet.balance_sheet_date else None,
            "income_statement_date": packet.income_statement_date.isoformat() if packet.income_statement_date else None,
            "accounts_receivable": packet.accounts_receivable,
            "missing_fields": packet.missing_fields,
            "sic_code": packet.sic_code,
            "sic_description": packet.sic_description,
            "components": components,
            "concept_counts": {
                "selected_points": len(packet.points),
            },
            "interest_income": {
                "tag": packet.interest_income_source,
                "method": packet.interest_income_method,
                "periods": [point.end.isoformat() for point in packet.points if point.concept in {INTEREST_PRIMARY_CONCEPT, INTEREST_BUNDLED_CONCEPT, INTEREST_UPPER_BOUNDARY_CONCEPT}],
                "forms": [point.form for point in packet.points if point.concept in {INTEREST_PRIMARY_CONCEPT, INTEREST_BUNDLED_CONCEPT, INTEREST_UPPER_BOUNDARY_CONCEPT}],
                "fallback_step": packet.interest_income_fallback_step,
                "fallback_disclaimer": packet.interest_income_disclaimer,
                "calculationDetails": packet.interest_income_calculation_details,
                "selected_tags_by_period": [
                    {"period": point.end.isoformat(), "tag": point.concept}
                    for point in packet.points
                    if point.concept in {INTEREST_PRIMARY_CONCEPT, INTEREST_BUNDLED_CONCEPT, INTEREST_UPPER_BOUNDARY_CONCEPT}
                ],
            },
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.session.flush()
        return row

    def _safe_ratio_value(self, raw_value: Any) -> float | None:
        value = _to_float(raw_value)
        if value is None:
            return None
        if abs(value) >= RATIO_NUMERIC_LIMIT:
            return None
        return value

    def _upsert_screen_result(
        self,
        company: Company,
        filing: Filing,
        normalized: NormalizedFinancial,
        data_source: str,
        placeholder_reason: str | None,
    ) -> HalalScreenResult:
        row = self.session.scalar(
            select(HalalScreenResult).where(
                HalalScreenResult.company_id == company.id,
                HalalScreenResult.filing_id == filing.id,
            )
        )
        if row is None:
            row = HalalScreenResult(company_id=company.id, filing_id=filing.id)
            self.session.add(row)

        if data_source == "sec_placeholder":
            row.debt_ratio = None
            row.interest_income_ratio = None
            row.cash_ratio = None
            row.halal_status = "Questionable / Needs Scholar Review"
            row.data_source = "sec_placeholder"
            row.source_filing_date = None
            row.mapped_tags_json = {"placeholder": True, "reason": placeholder_reason}
            row.reasoning_json = {
                "placeholder": True,
                "reason": placeholder_reason,
                "breakdown": [
                    {
                        "check": "SEC Filing Coverage",
                        "value": "Unavailable",
                        "threshold": "Recent 10-Q/10-K + company facts",
                        "result": "Needs Review",
                        "result_class": "unknown",
                    }
                ],
            }
            self.session.flush()
            return row

        payload = {
            "sector": company.sector or "",
            "industry": company.industry or "",
            "market_cap": float(normalized.market_cap) if normalized.market_cap is not None else None,
            "total_debt": float(normalized.total_debt) if normalized.total_debt is not None else 0.0,
            "cash": float(normalized.cash_and_equivalents) if normalized.cash_and_equivalents is not None else 0.0,
            "total_revenue": float(normalized.total_revenue) if normalized.total_revenue is not None else None,
            "non_halal_income": float(normalized.interest_income) if normalized.interest_income is not None else 0.0,
        }
        screening = screen_stock(payload)

        row.debt_ratio = self._safe_ratio_value(screening.get("debt_ratio"))
        row.interest_income_ratio = self._safe_ratio_value(screening.get("income_ratio"))
        row.cash_ratio = self._safe_ratio_value(screening.get("cash_ratio"))
        row.halal_status = screening.get("result") or "Questionable / Needs Scholar Review"
        row.data_source = "edgar_xbrl"
        row.source_filing_date = filing.filing_date
        row.mapped_tags_json = normalized.source_metadata_json
        row.reasoning_json = {
            "reason": screening.get("reason"),
            "breakdown": screening.get("breakdown"),
            "used_filing": {
                "accession_number": filing.accession_number,
                "filing_type": filing.filing_type,
                "filing_date": str(filing.filing_date),
            },
        }
        self.session.flush()
        return row

    def _fetch_yfinance_snapshot(self, ticker: str, audit: RunAudit) -> YFinanceSnapshot:
        market_cap: float | None = None
        sector: str | None = None
        industry: str | None = None
        shares_outstanding: float | None = None
        latest_closing_price: float | None = None
        try:
            info = yf.Ticker(ticker).info or {}
            market_cap = _to_float(info.get("marketCap"))
            sector = str(info.get("sector") or "").strip() or None
            industry = str(info.get("industry") or "").strip() or None
            shares_outstanding = _to_float(info.get("sharesOutstanding"))
            latest_closing_price = _to_float(
                info.get("regularMarketPrice")
                or info.get("currentPrice")
                or info.get("previousClose")
            )
            if market_cap is None:
                audit.record_yfinance_error(ticker, "marketCap missing")
        except Exception as exc:  # pragma: no cover - network path
            audit.record_yfinance_error(ticker, str(exc))
        finally:
            time.sleep(0.1)
        return YFinanceSnapshot(
            market_cap=market_cap,
            sector=sector,
            industry=industry,
            shares_outstanding=shares_outstanding,
            latest_closing_price=latest_closing_price,
        )

    async def _fetch_packets(self, tickers: list[str], audit: RunAudit) -> dict[str, TickerEdgarPacket]:
        if not tickers:
            return {}

        async with AsyncEdgarClient() as client:
            mapping = await client.fetch_ticker_mapping()
            ticker_sem = asyncio.Semaphore(40)

            async def _worker(symbol: str) -> tuple[str, TickerEdgarPacket]:
                async with ticker_sem:
                    packet = await _fetch_ticker_packet(client, mapping, symbol, audit)
                    return symbol, packet

            results = await asyncio.gather(*(_worker(symbol) for symbol in tickers))
            return {ticker: packet for ticker, packet in results}

    def _persist_packet(
        self,
        packet: TickerEdgarPacket,
        audit: RunAudit,
    ) -> RefreshSummary:
        company = self._ensure_company(packet)
        yfinance_data = self._fetch_yfinance_snapshot(packet.ticker, audit)
        if yfinance_data.sector:
            company.sector = yfinance_data.sector
        if yfinance_data.industry:
            company.industry = yfinance_data.industry
        sector_value = company.sector
        industry_value = company.industry

        placeholder_reason = packet.placeholder_reason
        if packet.cik is None:
            placeholder_reason = packet.placeholder_reason or "CIK not found in SEC ticker map."

        if placeholder_reason:
            filing_row = {
                "accession_number": PLACEHOLDER_ACCESSION,
                "filing_type": PLACEHOLDER_FILING_TYPE,
                "filing_date": datetime.now(UTC).date(),
                "fiscal_year": None,
                "fiscal_period": None,
            }
            filing = self._upsert_filing(company.id, filing_row)
            packet.total_debt = None
            packet.total_cash = None
            packet.accounts_receivable = None
            packet.total_revenue = None
            packet.interest_income = None
            packet.balance_sheet_date = None
            packet.income_statement_date = None
            packet.points = []
            normalized = self._upsert_normalized(
                company.id,
                filing.id,
                packet,
                yfinance_data,
                sector_value,
                industry_value,
            )
            self._store_raw_facts(company.id, filing.id, [])
            self._upsert_screen_result(
                company,
                filing,
                normalized,
                "sec_placeholder",
                placeholder_reason,
            )
            company.updated_at = datetime.now(UTC)
            return RefreshSummary(
                ticker=packet.ticker,
                processed_filings=1,
                skipped_filings=0,
                status="ok",
                message=placeholder_reason,
            )

        filing_row = {
            "accession_number": packet.primary_accession_number,
            "filing_type": packet.primary_filing_type,
            "filing_date": packet.primary_filing_date,
            "fiscal_year": packet.primary_filing_date.year,
            "fiscal_period": None,
        }
        filing = self._upsert_filing(company.id, filing_row)
        normalized = self._upsert_normalized(
            company.id,
            filing.id,
            packet,
            yfinance_data,
            sector_value,
            industry_value,
        )
        raw_rows = _points_to_raw_rows(packet.points)
        self._store_raw_facts(company.id, filing.id, raw_rows)
        self._upsert_screen_result(company, filing, normalized, "edgar_xbrl", None)
        company.updated_at = datetime.now(UTC)
        return RefreshSummary(
            ticker=packet.ticker,
            processed_filings=1,
            skipped_filings=0,
            status="ok",
        )

    def _emit_summary(self, audit: RunAudit, summaries: list[RefreshSummary]) -> None:
        successful = sum(1 for summary in summaries if summary.status == "ok")
        runtime = audit.runtime_seconds()
        minutes, seconds = divmod(runtime, 60)
        missing_xbrl_tickers = _unique_ticker_count(audit.missing_xbrl)
        yfinance_error_tickers = _unique_ticker_count(audit.yfinance_errors)
        foreign_filer_tickers = _unique_ticker_count(audit.foreign_filer)
        no_xbrl_tickers = _unique_ticker_count(audit.no_xbrl)
        LOGGER.info("✅ Successfully processed: %s tickers", successful)
        LOGGER.info("⚠️  Missing XBRL data:     %s tickers  (see %s)", missing_xbrl_tickers, LOG_FILES["missing_xbrl"])
        LOGGER.info("❌  CIK not found:          %s tickers  (see %s)", len(audit.cik_not_found), LOG_FILES["cik_not_found"])
        LOGGER.info("❌  yfinance errors:        %s tickers  (see %s)", yfinance_error_tickers, LOG_FILES["yfinance_errors"])
        LOGGER.info("⚠️  Foreign filers:         %s tickers  (see %s)", foreign_filer_tickers, LOG_FILES["foreign_filer"])
        LOGGER.info("⚠️  No XBRL data:           %s tickers  (see %s)", no_xbrl_tickers, LOG_FILES["no_xbrl"])
        LOGGER.info("⏱️  Total runtime:          %d min %02d sec", minutes, seconds)

    def refresh_tracked_companies(self, *, limit: int = 0, force: bool = False, max_filings: int = 8) -> list[RefreshSummary]:
        del force  # Refresh path always updates latest snapshot.
        del max_filings  # Concept-based ingestion is independent from filing count.
        query = select(Company.ticker).order_by(Company.ticker.asc())
        if limit > 0:
            query = query.limit(limit)
        tickers = [row[0] for row in self.session.execute(query).all()]
        audit = RunAudit()
        summaries: list[RefreshSummary] = []

        packets = asyncio.run(self._fetch_packets(tickers, audit))
        for ticker in tickers:
            packet = packets.get(ticker)
            if packet is None:
                message = "Pipeline packet missing."
                audit.record_pipeline_error(ticker, message)
                summaries.append(
                    RefreshSummary(
                        ticker=ticker,
                        processed_filings=0,
                        skipped_filings=0,
                        status="error",
                        message=message,
                    )
                )
                continue

            try:
                summary = self._persist_packet(packet, audit)
                self.session.commit()
                summaries.append(summary)
            except Exception as exc:  # pragma: no cover - defensive scheduler loop
                self.session.rollback()
                audit.record_pipeline_error(ticker, str(exc))
                LOGGER.exception("Refresh failed for ticker %s", ticker)
                summaries.append(
                    RefreshSummary(
                        ticker=ticker,
                        processed_filings=0,
                        skipped_filings=0,
                        status="error",
                        message=str(exc),
                    )
                )

        audit.flush_logs()
        self._emit_summary(audit, summaries)
        return summaries

    def refresh_ticker(self, ticker: str, *, force: bool = False, max_filings: int = 8) -> RefreshSummary:
        del force
        del max_filings
        symbol = ticker.strip().upper()
        audit = RunAudit()
        packets = asyncio.run(self._fetch_packets([symbol], audit))
        packet = packets.get(symbol)
        if packet is None:
            message = "Pipeline packet missing."
            audit.record_pipeline_error(symbol, message)
            audit.flush_logs()
            return RefreshSummary(
                ticker=symbol,
                processed_filings=0,
                skipped_filings=0,
                status="error",
                message=message,
            )

        try:
            summary = self._persist_packet(packet, audit)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            audit.record_pipeline_error(symbol, str(exc))
            LOGGER.exception("Refresh failed for ticker %s", symbol)
            summary = RefreshSummary(
                ticker=symbol,
                processed_filings=0,
                skipped_filings=0,
                status="error",
                message=str(exc),
            )
        audit.flush_logs()
        self._emit_summary(audit, [summary])
        return summary


def weekly_sec_refresh(*, limit: int = 0, force: bool = False, max_filings: int = 8) -> list[RefreshSummary]:
    """Scheduled weekly refresh job that updates all tracked companies."""
    with session_scope() as session:
        service = SecRefreshService(session)
        summaries = service.refresh_tracked_companies(
            limit=limit,
            force=force,
            max_filings=max_filings,
        )
    return summaries


def refresh_single_ticker(ticker: str, *, force: bool = False, max_filings: int = 8) -> RefreshSummary:
    """Admin/ops helper for manually refreshing one ticker."""
    with session_scope() as session:
        service = SecRefreshService(session)
        summary = service.refresh_ticker(ticker, force=force, max_filings=max_filings)
    return summary


def latest_cached_screen_row(session: Session, ticker: str) -> tuple[Company, Filing, NormalizedFinancial, HalalScreenResult] | None:
    """Return latest locally cached screening record for API/UI read path."""
    query = (
        select(Company, Filing, NormalizedFinancial, HalalScreenResult)
        .join(Filing, Filing.company_id == Company.id)
        .join(
            NormalizedFinancial,
            (NormalizedFinancial.company_id == Company.id)
            & (NormalizedFinancial.filing_id == Filing.id),
        )
        .join(
            HalalScreenResult,
            (HalalScreenResult.company_id == Company.id)
            & (HalalScreenResult.filing_id == Filing.id),
        )
        .where(Company.ticker == ticker.upper().strip())
        .order_by(desc(Filing.filing_date), desc(Filing.created_at))
        .limit(1)
    )
    row = session.execute(query).first()
    if row is None:
        return None
    return row[0], row[1], row[2], row[3]
