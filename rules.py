"""AAOIFI screening logic for Halal Stock Checker."""

from __future__ import annotations

PROHIBITED_KEYWORDS = (
    "bank",
    "financ",
    "insurance",
    "gambling",
    "alcohol",
    "tobacco",
    "adult",
    "entertainment",
    "weapon",
    "defense",
    "cannabis",
    "marijuana",
    "pork",
    "riba",
)

DEBT_THRESHOLD = 0.33
CASH_THRESHOLD = 0.33
INCOME_THRESHOLD = 0.05
MARGIN = 0.05

UNKNOWN_PROFILE_VALUES = frozenset({"", "unknown", "n/a", "na", "none"})


def _clean_profile_text(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if text.lower() in UNKNOWN_PROFILE_VALUES:
        return ""
    return text


def _profile_text(sector: str, industry: str) -> str:
    parts = []
    for part in (_clean_profile_text(sector), _clean_profile_text(industry)):
        if part:
            parts.append(part)
    return " ".join(parts)


def _is_profile_unknown(sector: str, industry: str) -> bool:
    return _profile_text(sector, industry) == ""


def _business_display_value(sector: str, industry: str) -> str:
    sector = _clean_profile_text(sector)
    industry = _clean_profile_text(industry)
    if sector and industry:
        return f"{sector} — {industry}"
    if sector:
        return sector
    if industry:
        return industry
    return "Unknown"


def _contains_prohibited(text: str) -> str | None:
    text_lower = (text or "").lower()
    for kw in PROHIBITED_KEYWORDS:
        if kw in text_lower:
            return kw
    return None


def _ratio_status(value: float | None, threshold: float, unavailable: bool) -> str:
    if unavailable or value is None:
        return "unavailable"
    if value > threshold:
        return "fail"
    if value > (threshold - MARGIN):
        return "borderline"
    return "pass"


def _format_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def screen_stock(data: dict) -> dict:
    sector = data.get("sector") or ""
    industry = data.get("industry") or ""
    profile_unknown = _is_profile_unknown(sector, industry)
    profile_text = _profile_text(sector, industry)
    prohibited_kw = _contains_prohibited(profile_text) if profile_text else None

    market_cap = data.get("market_cap")
    total_debt = data.get("total_debt") or 0.0
    cash = data.get("cash") or 0.0
    total_revenue = data.get("total_revenue")
    non_halal_income = data.get("non_halal_income") or 0.0

    debt_ratio: float | None = None
    cash_ratio: float | None = None
    income_ratio: float | None = None

    debt_unavailable = market_cap is None or market_cap == 0
    cash_unavailable = debt_unavailable
    income_unavailable = total_revenue is None or total_revenue == 0

    if not debt_unavailable:
        debt_ratio = total_debt / market_cap
    if not cash_unavailable:
        cash_ratio = cash / market_cap
    if not income_unavailable:
        income_ratio = non_halal_income / total_revenue
    elif non_halal_income == 0:
        income_ratio = 0.0
        income_unavailable = False

    debt_status = _ratio_status(debt_ratio, DEBT_THRESHOLD, debt_unavailable)
    cash_status = _ratio_status(cash_ratio, CASH_THRESHOLD, cash_unavailable)
    income_status = _ratio_status(income_ratio, INCOME_THRESHOLD, income_unavailable)

    breakdown = []

    if profile_unknown:
        business_display = "Needs Review"
        business_result_class = "unknown"
    elif prohibited_kw:
        business_display = "Fail"
        business_result_class = "fail"
    else:
        business_display = "Pass"
        business_result_class = "pass"

    breakdown.append(
        {
            "check": "Business Sector",
            "value": _business_display_value(sector, industry),
            "threshold": "Permitted",
            "result": business_display,
            "result_class": business_result_class,
        }
    )

    def _row_result(status: str) -> tuple[str, str]:
        if status == "pass":
            return "Pass", "pass"
        if status == "fail":
            return "Fail", "fail"
        if status == "borderline":
            return "Borderline", "unknown"
        return "Needs Review", "unknown"

    debt_res, debt_cls = _row_result(debt_status)
    cash_res, cash_cls = _row_result(cash_status)
    income_res, income_cls = _row_result(income_status)

    breakdown.append(
        {
            "check": "Debt / Market Cap",
            "value": _format_pct(debt_ratio),
            "threshold": "< 33%",
            "result": debt_res,
            "result_class": debt_cls,
        }
    )
    breakdown.append(
        {
            "check": "Cash / Market Cap",
            "value": _format_pct(cash_ratio),
            "threshold": "< 33%",
            "result": cash_res,
            "result_class": cash_cls,
        }
    )
    breakdown.append(
        {
            "check": "Non-Halal Income Ratio",
            "value": _format_pct(income_ratio),
            "threshold": "< 5%",
            "result": income_res,
            "result_class": income_cls,
        }
    )

    financial_statuses = [debt_status, cash_status, income_status]
    fails = [s for s in financial_statuses if s == "fail"]
    borderlines = [s for s in financial_statuses if s == "borderline"]
    unavailables = [s for s in financial_statuses if s == "unavailable"]

    if prohibited_kw:
        result = "Not Halal"
        reason = (
            f"The company's sector/industry ({_business_display_value(sector, industry)}) "
            f"appears to involve prohibited activities (matched: '{prohibited_kw}'). "
            "Per AAOIFI standards, the business activity screen fails."
        )
    elif fails:
        result = "Not Halal"
        fail_names = []
        if debt_status == "fail":
            fail_names.append(f"Debt/Market Cap ({_format_pct(debt_ratio)}, limit 33%)")
        if cash_status == "fail":
            fail_names.append(f"Cash/Market Cap ({_format_pct(cash_ratio)}, limit 33%)")
        if income_status == "fail":
            fail_names.append(
                f"Non-Halal Income/Revenue ({_format_pct(income_ratio)}, limit 5%)"
            )
        reason = (
            "One or more financial ratios exceed AAOIFI thresholds: "
            + "; ".join(fail_names)
            + "."
        )
    elif profile_unknown:
        result = "Questionable / Needs Scholar Review"
        reason = (
            "Sector and industry could not be verified from available data. "
            "A scholar should confirm the company's business activities before investing."
        )
    elif borderlines:
        result = "Questionable / Needs Scholar Review"
        reason = "One or more ratios are close to the permissible limit."
    elif unavailables:
        result = "Questionable / Needs Scholar Review"
        reason = "Insufficient data to complete full screening."
    else:
        result = "Halal"
        reason = "Passes all AAOIFI business and financial screens."

    return {
        "result": result,
        "reason": reason,
        "breakdown": breakdown,
        "debt_ratio": debt_ratio,
        "cash_ratio": cash_ratio,
        "income_ratio": income_ratio,
        "profile_unknown": profile_unknown,
        "business_pass": prohibited_kw is None and not profile_unknown,
    }