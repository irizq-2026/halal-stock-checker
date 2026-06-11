"""Normalization layer for SEC XBRL company facts."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

LOGGER = logging.getLogger(__name__)


REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "Revenues",
]

INTEREST_PRIMARY_TAG = "InvestmentIncomeInterest"
INTEREST_BUNDLED_TAG = "InvestmentIncomeInterestAndDividend"
INTEREST_UPPER_BOUNDARY_TAG = "NonoperatingIncomeExpense"

INTEREST_INCOME_TAGS = [
    INTEREST_PRIMARY_TAG,
    INTEREST_BUNDLED_TAG,
    INTEREST_UPPER_BOUNDARY_TAG,
    "InterestIncomeExpenseNet",
    "InterestIncomeOperating",
    "InterestAndDividendIncomeOperating",
]

DEBT_TAGS = [
    "LongTermDebt",
    "LongTermDebtAndCapitalLeaseObligations",
    "DebtInstrumentCarryingAmount",
    "DebtCurrent",
    "LongTermDebtCurrent",
]

CASH_TAGS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
]

TOTAL_ASSETS_TAGS = [
    "Assets",
]

OPERATING_INCOME_TAGS = [
    "OperatingIncomeLoss",
]

NET_INCOME_TAGS = [
    "NetIncomeLoss",
]

SHARES_OUTSTANDING_TAGS = [
    "EntityCommonStockSharesOutstanding",
    "CommonStockSharesOutstanding",
]

MARKET_CAP_TAGS = [
    "EntityPublicFloat",
    "MarketCapitalization",
]

CANONICAL_TAGS = {
    "total_revenue": REVENUE_TAGS,
    "interest_income": INTEREST_INCOME_TAGS,
    "total_debt": DEBT_TAGS,
    "cash_and_equivalents": CASH_TAGS,
    "total_assets": TOTAL_ASSETS_TAGS,
    "market_cap": MARKET_CAP_TAGS,
    "operating_income": OPERATING_INCOME_TAGS,
    "net_income": NET_INCOME_TAGS,
    "shares_outstanding": SHARES_OUTSTANDING_TAGS,
}

ALL_TRACKED_TAGS = sorted({tag for tags in CANONICAL_TAGS.values() for tag in tags})


@dataclass(frozen=True)
class FactPoint:
    taxonomy: str
    tag: str
    unit: str
    value: float
    period_start: date | None
    period_end: date | None
    filed_date: date | None
    frame: str | None
    form: str | None
    accession_number: str | None
    fiscal_year: int | None
    fiscal_period: str | None


def _json_safe(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:
        return None
    return numeric


def build_fact_index(company_facts: dict[str, Any]) -> dict[str, list[FactPoint]]:
    """Flatten SEC companyfacts payload into a tag-indexed map."""
    indexed: dict[str, list[FactPoint]] = {}
    facts = company_facts.get("facts") or {}
    for taxonomy, taxonomy_facts in facts.items():
        if not isinstance(taxonomy_facts, dict):
            continue
        for tag, tag_payload in taxonomy_facts.items():
            units = (tag_payload or {}).get("units") or {}
            for unit, datapoints in units.items():
                if not isinstance(datapoints, list):
                    continue
                for point in datapoints:
                    value = _parse_float((point or {}).get("val"))
                    if value is None:
                        continue
                    fact = FactPoint(
                        taxonomy=taxonomy,
                        tag=tag,
                        unit=unit,
                        value=value,
                        period_start=_parse_date((point or {}).get("start")),
                        period_end=_parse_date((point or {}).get("end")),
                        filed_date=_parse_date((point or {}).get("filed")),
                        frame=(point or {}).get("frame"),
                        form=(point or {}).get("form"),
                        accession_number=(point or {}).get("accn"),
                        fiscal_year=(point or {}).get("fy"),
                        fiscal_period=(point or {}).get("fp"),
                    )
                    indexed.setdefault(tag, []).append(fact)
    return indexed


def _fact_sort_key(point: FactPoint, prefer_quarterly: bool) -> tuple[int, date, date]:
    period_end = point.period_end or date.min
    filed_date = point.filed_date or date.min
    quarterly_bonus = 1 if prefer_quarterly and _is_quarterly(point) else 0
    return quarterly_bonus, filed_date, period_end


def get_first_matching_fact(
    tags: list[str],
    facts: dict[str, list[FactPoint]],
    *,
    as_of_date: date | None = None,
    prefer_quarterly: bool = False,
) -> tuple[str | None, FactPoint | None]:
    """Return first best matching fact from tag priority list."""
    for tag in tags:
        candidates = facts.get(tag, [])
        if as_of_date is not None:
            candidates = [
                point
                for point in candidates
                if point.filed_date is None or point.filed_date <= as_of_date
            ]
        if not candidates:
            continue
        best = sorted(
            candidates,
            key=lambda point: _fact_sort_key(point, prefer_quarterly),
            reverse=True,
        )[0]
        return tag, best
    return None, None


def _duration_days(point: FactPoint) -> int | None:
    if point.period_start and point.period_end:
        return (point.period_end - point.period_start).days
    return None


def _is_quarterly(point: FactPoint) -> bool:
    fp = (point.fiscal_period or "").upper()
    if fp in {"Q1", "Q2", "Q3", "Q4"}:
        return True
    days = _duration_days(point)
    if days is None:
        return False
    return 70 <= days <= 120


def _is_annual(point: FactPoint) -> bool:
    fp = (point.fiscal_period or "").upper()
    if fp in {"FY", "CY"}:
        return True
    form = (point.form or "").upper()
    if form.startswith("10-K"):
        return True
    days = _duration_days(point)
    if days is None:
        return False
    return days >= 300


def _dedupe_by_period_end(points: list[FactPoint]) -> list[FactPoint]:
    deduped: dict[date, FactPoint] = {}
    for point in points:
        if point.period_end is None:
            continue
        existing = deduped.get(point.period_end)
        if existing is None:
            deduped[point.period_end] = point
            continue
        if (point.filed_date or date.min) >= (existing.filed_date or date.min):
            deduped[point.period_end] = point
    return sorted(
        deduped.values(),
        key=lambda item: (item.period_end or date.min, item.filed_date or date.min),
        reverse=True,
    )


def _calculate_ttm(points: list[FactPoint], *, as_of_date: date | None) -> tuple[float | None, dict[str, Any]]:
    candidates = points
    if as_of_date is not None:
        candidates = [
            point for point in candidates if point.filed_date is None or point.filed_date <= as_of_date
        ]
    if not candidates:
        return None, {"method": "missing", "periods": [], "forms": [], "latest_period_end": None, "latest_filed_date": None}

    quarterly = _dedupe_by_period_end([point for point in candidates if _is_quarterly(point)])
    if len(quarterly) >= 4:
        latest_four = quarterly[:4]
        first_period = latest_four[-1].period_end
        last_period = latest_four[0].period_end
        if first_period and last_period and (last_period - first_period).days <= 500:
            return (
                sum(point.value for point in latest_four),
                {
                    "method": "ttm_quarters",
                    "periods": [str(point.period_end) for point in latest_four if point.period_end],
                    "forms": [point.form for point in latest_four],
                    "latest_period_end": str(latest_four[0].period_end) if latest_four[0].period_end else None,
                    "latest_filed_date": str(latest_four[0].filed_date) if latest_four[0].filed_date else None,
                },
            )

    annual = _dedupe_by_period_end([point for point in candidates if _is_annual(point)])
    if annual:
        point = annual[0]
        return (
            point.value,
            {
                "method": "annual_fallback",
                "periods": [str(point.period_end)] if point.period_end else [],
                "forms": [point.form],
                "latest_period_end": str(point.period_end) if point.period_end else None,
                "latest_filed_date": str(point.filed_date) if point.filed_date else None,
            },
        )

    best = sorted(
        candidates,
        key=lambda point: (point.filed_date or date.min, point.period_end or date.min),
        reverse=True,
    )[0]
    return (
        best.value,
        {
            "method": "latest_fallback",
            "periods": [str(best.period_end)] if best.period_end else [],
            "forms": [best.form],
            "latest_period_end": str(best.period_end) if best.period_end else None,
            "latest_filed_date": str(best.filed_date) if best.filed_date else None,
        },
    )


def _is_non_zero(value: float | None) -> bool:
    return value is not None and value != 0.0


def _filter_as_of(points: list[FactPoint], *, as_of_date: date | None) -> list[FactPoint]:
    if as_of_date is None:
        return list(points)
    return [point for point in points if point.filed_date is None or point.filed_date <= as_of_date]


def _period_label_from_period_end(period_end: str | None) -> str:
    if not period_end:
        return "Unknown Period"
    try:
        parsed = datetime.strptime(period_end, "%Y-%m-%d").date()
    except ValueError:
        return period_end
    quarter = ((parsed.month - 1) // 3) + 1
    return f"Q{quarter} {parsed.year}"


def _log_ratio3_source(ticker: str | None, periods: list[str], source_tag: str) -> None:
    ticker_label = (ticker or "UNKNOWN").upper()
    if not periods:
        message = f"[Ratio3Source] Unknown Period {ticker_label} → {source_tag}"
        LOGGER.info(message)
        print(message)
        return
    for period in periods:
        message = f"[Ratio3Source] {_period_label_from_period_end(period)} {ticker_label} → {source_tag}"
        LOGGER.info(message)
        print(message)


def _merge_interest_metadata(
    *,
    tag: str | None,
    base_meta: dict[str, Any],
    fallback_step: str | None,
    fallback_disclaimer: str | None,
) -> dict[str, Any]:
    return {
        "tag": tag,
        "method": base_meta.get("method"),
        "periods": base_meta.get("periods", []),
        "forms": base_meta.get("forms", []),
        "fallback_step": fallback_step,
        "fallback_disclaimer": fallback_disclaimer,
    }


def _resolve_interest_income_with_fallback(
    facts: dict[str, list[FactPoint]],
    *,
    as_of_date: date | None,
    ticker: str | None,
) -> tuple[float | None, dict[str, Any]]:
    primary_value, primary_meta = _calculate_ttm(
        _filter_as_of(facts.get(INTEREST_PRIMARY_TAG, []), as_of_date=as_of_date),
        as_of_date=as_of_date,
    )
    if _is_non_zero(primary_value):
        _log_ratio3_source(ticker, primary_meta.get("periods", []), INTEREST_PRIMARY_TAG)
        return (
            primary_value,
            _merge_interest_metadata(
                tag=INTEREST_PRIMARY_TAG,
                base_meta=primary_meta,
                fallback_step=None,
                fallback_disclaimer=None,
            ),
        )

    bundled_value, bundled_meta = _calculate_ttm(
        _filter_as_of(facts.get(INTEREST_BUNDLED_TAG, []), as_of_date=as_of_date),
        as_of_date=as_of_date,
    )
    if _is_non_zero(bundled_value):
        _log_ratio3_source(ticker, bundled_meta.get("periods", []), INTEREST_BUNDLED_TAG)
        return (
            bundled_value,
            _merge_interest_metadata(
                tag=INTEREST_BUNDLED_TAG,
                base_meta=bundled_meta,
                fallback_step="step2",
                fallback_disclaimer=(
                    "⚠️ Interest & dividend income reported as a combined figure. "
                    "This ratio may be slightly overstated if dividend income is included."
                ),
            ),
        )

    upper_value, upper_meta = _calculate_ttm(
        _filter_as_of(facts.get(INTEREST_UPPER_BOUNDARY_TAG, []), as_of_date=as_of_date),
        as_of_date=as_of_date,
    )
    if upper_value is not None:
        _log_ratio3_source(ticker, upper_meta.get("periods", []), INTEREST_UPPER_BOUNDARY_TAG)
        return (
            upper_value,
            _merge_interest_metadata(
                tag=INTEREST_UPPER_BOUNDARY_TAG,
                base_meta=upper_meta,
                fallback_step="step3",
                fallback_disclaimer=(
                    "⚠️ Interest income not separately reported for this period. "
                    "Non-operating income used as the upper boundary. "
                    "Ratio 3 reflects a conservative ceiling, not an exact figure."
                ),
            ),
        )

    return (
        None,
        _merge_interest_metadata(
            tag=None,
            base_meta={"method": "missing", "periods": [], "forms": []},
            fallback_step=None,
            fallback_disclaimer=None,
        ),
    )


def normalize_financials_for_filing(
    company_facts: dict[str, Any],
    filing_date: date | None,
    ticker: str | None = None,
) -> tuple[dict[str, float | None], dict[str, Any], list[dict[str, Any]]]:
    """Compute normalized values and explain which tags were used."""
    facts_index = build_fact_index(company_facts)
    normalized: dict[str, float | None] = {}
    mapped_tags: dict[str, Any] = {}
    raw_rows: list[dict[str, Any]] = []

    for tag in ALL_TRACKED_TAGS:
        for point in facts_index.get(tag, []):
            raw_rows.append(
                {
                    "taxonomy": point.taxonomy,
                    "tag": point.tag,
                    "unit": point.unit,
                    "value": point.value,
                    "period_start": point.period_start,
                    "period_end": point.period_end,
                    "filed_date": point.filed_date,
                    "frame": point.frame,
                    "raw_json": _json_safe(asdict(point)),
                }
            )

    flow_fields = {"total_revenue", "interest_income", "operating_income", "net_income"}
    for field_name, tags in CANONICAL_TAGS.items():
        if field_name == "interest_income":
            value, metadata = _resolve_interest_income_with_fallback(
                facts_index,
                as_of_date=filing_date,
                ticker=ticker,
            )
            normalized[field_name] = value
            mapped_tags[field_name] = metadata
            continue

        if field_name in flow_fields:
            used_tag: str | None = None
            selected_value: float | None = None
            selected_metadata: dict[str, Any] = {
                "method": "missing",
                "periods": [],
                "forms": [],
                "latest_period_end": None,
                "latest_filed_date": None,
            }
            selected_rank = (date.min, date.min, -1)
            for tag in tags:
                value, metadata = _calculate_ttm(facts_index.get(tag, []), as_of_date=filing_date)
                if value is None:
                    continue
                latest_period_end = _parse_date(metadata.get("latest_period_end")) or date.min
                latest_filed_date = _parse_date(metadata.get("latest_filed_date")) or date.min
                method_score = 1 if metadata.get("method") == "ttm_quarters" else 0
                rank = (latest_period_end, latest_filed_date, method_score)
                if rank > selected_rank:
                    selected_rank = rank
                    selected_value = value
                    selected_metadata = metadata
                    used_tag = tag

            normalized[field_name] = selected_value
            mapped_tags[field_name] = {
                "tag": used_tag,
                "method": selected_metadata.get("method"),
                "periods": selected_metadata.get("periods", []),
                "forms": selected_metadata.get("forms", []),
                "latest_period_end": selected_metadata.get("latest_period_end"),
                "latest_filed_date": selected_metadata.get("latest_filed_date"),
            }
            continue

        matched_tag, matched_point = get_first_matching_fact(
            tags,
            facts_index,
            as_of_date=filing_date,
            prefer_quarterly=True,
        )
        stale_discarded = False
        stale_age_days: int | None = None
        if field_name == "market_cap" and matched_point and filing_date:
            reference_date = matched_point.period_end or matched_point.filed_date
            if reference_date:
                stale_age_days = (filing_date - reference_date).days
                if stale_age_days > 550:
                    stale_discarded = True
                    matched_tag = None
                    matched_point = None

        normalized[field_name] = matched_point.value if matched_point else None
        mapped_tags[field_name] = {
            "tag": matched_tag,
            "period_end": str(matched_point.period_end) if matched_point and matched_point.period_end else None,
            "filed_date": str(matched_point.filed_date) if matched_point and matched_point.filed_date else None,
            "unit": matched_point.unit if matched_point else None,
            "form": matched_point.form if matched_point else None,
            "method": "latest_point_in_time",
            "stale_discarded": stale_discarded,
            "stale_age_days": stale_age_days,
        }

    return normalized, mapped_tags, raw_rows
