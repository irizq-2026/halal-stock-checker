"""Shared EDGAR XBRL filing/taxonomy helpers."""

from __future__ import annotations

from typing import Any

FILER_DOMESTIC = "DOMESTIC"
FILER_FPI_20F = "FPI_20F"
FILER_FPI_40F = "FPI_40F"
FILER_UNKNOWN = "UNKNOWN"

DOMESTIC_ANNUAL_FORMS = frozenset({"10-K", "10-K/A"})
DOMESTIC_QUARTERLY_FORMS = frozenset({"10-Q", "10-Q/A"})
FPI_ANNUAL_FORMS = frozenset({"20-F", "20-F/A", "40-F", "40-F/A"})
SUPPORTED_REPORT_FORMS = DOMESTIC_ANNUAL_FORMS | DOMESTIC_QUARTERLY_FORMS | FPI_ANNUAL_FORMS

DATA_FREQUENCY_ANNUAL = "annual"
DATA_FREQUENCY_QUARTERLY = "quarterly"

TAXONOMY_US_GAAP = "us-gaap"
TAXONOMY_IFRS_FULL = "ifrs-full"

CONCEPT_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "total_assets": {
        TAXONOMY_US_GAAP: ("Assets",),
        TAXONOMY_IFRS_FULL: ("Assets",),
    },
    "total_debt": {
        TAXONOMY_US_GAAP: (
            "LongTermDebt",
            "LongTermDebtAndCapitalLeaseObligations",
            "DebtAndCapitalLeaseObligations",
            "Liabilities",
        ),
        TAXONOMY_IFRS_FULL: (
            "BorrowingsAndPayablesToDepositors",
            "Borrowings",
            "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
            "LongtermBorrowings",
            "NoncurrentPortionOfNoncurrentBorrowings",
            "ShorttermBorrowings",
            "Liabilities",
        ),
    },
    "total_cash": {
        TAXONOMY_US_GAAP: (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "CashAndCashEquivalents",
        ),
        TAXONOMY_IFRS_FULL: (
            "CashAndCashEquivalents",
            "Cash",
            "ShorttermDepositsNotClassifiedAsCashEquivalents",
        ),
    },
    "accounts_receivable": {
        TAXONOMY_US_GAAP: (
            "AccountsReceivableNetCurrent",
            "ReceivablesNetCurrent",
            "AccountsAndNotesReceivableNet",
        ),
        TAXONOMY_IFRS_FULL: (
            "TradeAndOtherCurrentReceivables",
            "CurrentTradeReceivables",
            "TradeReceivables",
            "TradeAndOtherReceivables",
            "InterestReceivable",
            "CurrentLoansAndReceivables",
            "ReceivablesFromContractsWithCustomers",
            "OtherCurrentReceivables",
        ),
    },
    "total_revenue": {
        TAXONOMY_US_GAAP: (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
        TAXONOMY_IFRS_FULL: (
            "RevenueFromContractsWithCustomers",
            "Revenue",
            "RevenueFromSaleOfGoods",
            "RevenueFromRenderingOfServices",
        ),
    },
    "interest_income": {
        TAXONOMY_US_GAAP: (
            "InvestmentIncomeInterest",
            "InvestmentIncomeInterestAndDividend",
            "InterestAndDividendIncomeOperating",
            "InterestIncomeOperating",
            "InterestIncome",
        ),
        TAXONOMY_IFRS_FULL: (
            "InterestRevenueCalculatedUsingEffectiveInterestMethod",
            "InterestIncomeForFinancialAssetsMeasuredAtAmortisedCost",
            "InterestIncomeForFinancialAssetsNotAtFairValueThroughProfitOrLoss",
            "RevenueFromInterest",
            "InterestIncome",
            "InterestIncomeOnLoansAndReceivables",
            "InterestIncomeOnLoansAndAdvancesToCustomers",
            "FinanceIncome",
            "OtherFinanceIncomeCost",
        ),
    },
}


def normalize_form(form: Any) -> str:
    return str(form or "").upper().strip()


def is_supported_report_form(form: Any) -> bool:
    return normalize_form(form) in SUPPORTED_REPORT_FORMS


def is_quarterly_form(form: Any) -> bool:
    return normalize_form(form) in DOMESTIC_QUARTERLY_FORMS


def is_annual_form(form: Any) -> bool:
    return normalize_form(form) in DOMESTIC_ANNUAL_FORMS or normalize_form(form) in FPI_ANNUAL_FORMS


def is_fpi_filer_type(filer_type: str | None) -> bool:
    return filer_type in {FILER_FPI_20F, FILER_FPI_40F}


def detect_filer_type(submissions: dict[str, Any]) -> str:
    recent = ((submissions.get("filings") or {}).get("recent") or {})
    forms = [normalize_form(form) for form in (recent.get("form") or [])]
    if "20-F" in forms or "20-F/A" in forms:
        return FILER_FPI_20F
    if "40-F" in forms or "40-F/A" in forms:
        return FILER_FPI_40F
    if "10-K" in forms or "10-K/A" in forms:
        return FILER_DOMESTIC
    return FILER_UNKNOWN


def detect_taxonomy(facts: dict[str, Any]) -> str | None:
    if TAXONOMY_IFRS_FULL in facts and TAXONOMY_US_GAAP not in facts:
        return TAXONOMY_IFRS_FULL
    if TAXONOMY_US_GAAP in facts:
        return TAXONOMY_US_GAAP
    if TAXONOMY_IFRS_FULL in facts:
        return TAXONOMY_IFRS_FULL
    return None


def taxonomy_priority(facts: dict[str, Any]) -> tuple[str, ...]:
    detected = detect_taxonomy(facts)
    if detected == TAXONOMY_US_GAAP and TAXONOMY_IFRS_FULL in facts:
        return (TAXONOMY_US_GAAP, TAXONOMY_IFRS_FULL)
    if detected:
        return (detected,)
    return ()


def aliases_for(field_name: str, facts: dict[str, Any]) -> tuple[str, ...]:
    aliases: list[str] = []
    taxonomy_aliases = CONCEPT_ALIASES.get(field_name) or {}
    for taxonomy in taxonomy_priority(facts):
        aliases.extend(taxonomy_aliases.get(taxonomy) or ())
    return tuple(dict.fromkeys(aliases))

