"""Normalization layer for SEC XBRL company facts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any


REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "Revenues",
]

INTEREST_INCOME_TAGS = [
    "InterestIncomeExpenseNet",
    "InterestIncomeOperating",
    "InvestmentIncomeInterest",
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
        return None, {"method": "missing", "periods": []}

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
        },
    )


def normalize_financials_for_filing(
    company_facts: dict[str, Any],
    filing_date: date | None,
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
        if field_name in flow_fields:
            points: list[FactPoint] = []
            used_tag: str | None = None
            for tag in tags:
                bucket = facts_index.get(tag, [])
                if bucket:
                    used_tag = tag
                    points = bucket
                    break
            value, metadata = _calculate_ttm(points, as_of_date=filing_date)
            normalized[field_name] = value
            mapped_tags[field_name] = {
                "tag": used_tag,
                "method": metadata.get("method"),
                "periods": metadata.get("periods", []),
                "forms": metadata.get("forms", []),
            }
            continue

        matched_tag, matched_point = get_first_matching_fact(
            tags,
            facts_index,
            as_of_date=filing_date,
            prefer_quarterly=True,
        )
        normalized[field_name] = matched_point.value if matched_point else None
        mapped_tags[field_name] = {
            "tag": matched_tag,
            "period_end": str(matched_point.period_end) if matched_point and matched_point.period_end else None,
            "filed_date": str(matched_point.filed_date) if matched_point and matched_point.filed_date else None,
            "unit": matched_point.unit if matched_point else None,
            "form": matched_point.form if matched_point else None,
            "method": "latest_point_in_time",
        }

    return normalized, mapped_tags, raw_rows
