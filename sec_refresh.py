"""SEC ingestion pipeline and weekly refresh orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from db import session_scope
from models import Company, Filing, HalalScreenResult, NormalizedFinancial, RawFinancialFact
from normalization import normalize_financials_for_filing
from rules import screen_stock
from sec_client import SecApiClient

LOGGER = logging.getLogger(__name__)

SUPPORTED_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}


def _parse_submission_filings(submissions: dict[str, Any]) -> list[dict[str, Any]]:
    recent = ((submissions.get("filings") or {}).get("recent") or {})
    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    filing_dates = recent.get("filingDate") or []
    fiscal_years = recent.get("fy") or []
    fiscal_periods = recent.get("fp") or []
    rows: list[dict[str, Any]] = []
    total = min(len(forms), len(accessions), len(filing_dates))
    for idx in range(total):
        form = str(forms[idx] or "").strip().upper()
        if form not in SUPPORTED_FORMS:
            continue
        filing_date = filing_dates[idx]
        if not filing_date:
            continue
        rows.append(
            {
                "accession_number": str(accessions[idx]).strip(),
                "filing_type": form,
                "filing_date": datetime.strptime(str(filing_date), "%Y-%m-%d").date(),
                "fiscal_year": fiscal_years[idx] if idx < len(fiscal_years) else None,
                "fiscal_period": fiscal_periods[idx] if idx < len(fiscal_periods) else None,
            }
        )
    rows.sort(key=lambda row: row["filing_date"], reverse=True)
    return rows


@dataclass
class RefreshSummary:
    ticker: str
    processed_filings: int
    skipped_filings: int
    status: str
    message: str = ""


class SecRefreshService:
    """Handles SEC -> normalize -> Postgres refresh operations."""

    def __init__(self, session: Session, sec_client: SecApiClient | None = None) -> None:
        self.session = session
        self.sec_client = sec_client or SecApiClient()
        self._ticker_mapping_cache: dict[str, dict[str, str]] | None = None

    def _ticker_mapping(self) -> dict[str, dict[str, str]]:
        if self._ticker_mapping_cache is None:
            self._ticker_mapping_cache = self.sec_client.fetch_ticker_mapping()
        return self._ticker_mapping_cache

    def _ensure_company(self, ticker: str) -> Company | None:
        normalized_ticker = ticker.strip().upper()
        mapping = self._ticker_mapping().get(normalized_ticker)
        if not mapping:
            LOGGER.info("Ticker not found in SEC mapping: %s", normalized_ticker)
            return None
        company = self.session.scalar(
            select(Company).where(Company.ticker == normalized_ticker)
        )
        if company is None:
            company = Company(
                ticker=normalized_ticker,
                cik=mapping["cik"],
                company_name=mapping["company_name"],
            )
            self.session.add(company)
            self.session.flush()
            return company

        company.cik = mapping["cik"]
        if mapping["company_name"]:
            company.company_name = mapping["company_name"]
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

    def _already_processed(self, company_id: int, filing_id: int) -> bool:
        normalized = self.session.scalar(
            select(NormalizedFinancial.id).where(
                NormalizedFinancial.company_id == company_id,
                NormalizedFinancial.filing_id == filing_id,
            )
        )
        result = self.session.scalar(
            select(HalalScreenResult.id).where(
                HalalScreenResult.company_id == company_id,
                HalalScreenResult.filing_id == filing_id,
            )
        )
        return bool(normalized and result)

    def _store_raw_facts(self, company_id: int, filing_id: int, raw_rows: list[dict[str, Any]]) -> None:
        self.session.execute(
            delete(RawFinancialFact).where(
                RawFinancialFact.company_id == company_id,
                RawFinancialFact.filing_id == filing_id,
            )
        )
        if not raw_rows:
            return
        insert_rows = []
        for row in raw_rows:
            insert_rows.append(
                {
                    "company_id": company_id,
                    "filing_id": filing_id,
                    **row,
                }
            )
        self.session.bulk_insert_mappings(RawFinancialFact, insert_rows)

    def _upsert_normalized(
        self,
        company_id: int,
        filing_id: int,
        normalized: dict[str, float | None],
        mapped_tags: dict[str, Any],
    ) -> NormalizedFinancial:
        row = self.session.scalar(
            select(NormalizedFinancial).where(
                NormalizedFinancial.company_id == company_id,
                NormalizedFinancial.filing_id == filing_id,
            )
        )
        if row is None:
            row = NormalizedFinancial(
                company_id=company_id,
                filing_id=filing_id,
            )
            self.session.add(row)

        row.total_revenue = normalized.get("total_revenue")
        row.interest_income = normalized.get("interest_income")
        row.total_debt = normalized.get("total_debt")
        row.cash_and_equivalents = normalized.get("cash_and_equivalents")
        row.total_assets = normalized.get("total_assets")
        row.market_cap = normalized.get("market_cap")
        row.operating_income = normalized.get("operating_income")
        row.net_income = normalized.get("net_income")
        row.shares_outstanding = normalized.get("shares_outstanding")
        row.source_metadata_json = mapped_tags
        self.session.flush()
        return row

    def _upsert_screen_result(
        self,
        company: Company,
        filing: Filing,
        normalized: NormalizedFinancial,
    ) -> HalalScreenResult:
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
        row = self.session.scalar(
            select(HalalScreenResult).where(
                HalalScreenResult.company_id == company.id,
                HalalScreenResult.filing_id == filing.id,
            )
        )
        if row is None:
            row = HalalScreenResult(
                company_id=company.id,
                filing_id=filing.id,
            )
            self.session.add(row)

        row.debt_ratio = screening.get("debt_ratio")
        row.interest_income_ratio = screening.get("income_ratio")
        row.cash_ratio = screening.get("cash_ratio")
        row.halal_status = screening.get("result") or "Questionable / Needs Scholar Review"
        row.data_source = "sec_xbrl"
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

    def refresh_ticker(self, ticker: str, *, force: bool = False, max_filings: int = 8) -> RefreshSummary:
        company = self._ensure_company(ticker)
        if company is None:
            return RefreshSummary(
                ticker=ticker.upper(),
                processed_filings=0,
                skipped_filings=0,
                status="skipped",
                message="Ticker not available in SEC company ticker list.",
            )

        submissions = self.sec_client.fetch_company_submissions(company.cik)
        if not submissions:
            return RefreshSummary(
                ticker=company.ticker,
                processed_filings=0,
                skipped_filings=0,
                status="skipped",
                message="No SEC submissions returned for this company.",
            )

        company_name = str(submissions.get("name") or "").strip()
        if company_name:
            company.company_name = company_name
        sic_description = str(submissions.get("sicDescription") or "").strip()
        if sic_description:
            # SEC submissions expose SIC description but not richer sector data.
            company.industry = sic_description
            if not company.sector:
                company.sector = sic_description

        filing_rows = _parse_submission_filings(submissions)[:max_filings]
        if not filing_rows:
            return RefreshSummary(
                ticker=company.ticker,
                processed_filings=0,
                skipped_filings=0,
                status="skipped",
                message="No recent 10-Q or 10-K filings.",
            )

        company_facts = self.sec_client.fetch_company_facts(company.cik)
        if not company_facts:
            return RefreshSummary(
                ticker=company.ticker,
                processed_filings=0,
                skipped_filings=0,
                status="skipped",
                message="No SEC company facts data available.",
            )

        processed = 0
        skipped = 0
        for filing_row in filing_rows:
            filing = self._upsert_filing(company.id, filing_row)
            if not force and self._already_processed(company.id, filing.id):
                skipped += 1
                continue

            normalized_payload, mapped_tags, raw_rows = normalize_financials_for_filing(
                company_facts,
                filing.filing_date,
            )
            self._store_raw_facts(company.id, filing.id, raw_rows)
            normalized = self._upsert_normalized(company.id, filing.id, normalized_payload, mapped_tags)
            self._upsert_screen_result(company, filing, normalized)
            processed += 1

        company.updated_at = datetime.now(timezone.utc)
        return RefreshSummary(
            ticker=company.ticker,
            processed_filings=processed,
            skipped_filings=skipped,
            status="ok",
        )

    def refresh_tracked_companies(self, *, limit: int = 0, force: bool = False, max_filings: int = 8) -> list[RefreshSummary]:
        query = select(Company.ticker).order_by(Company.ticker.asc())
        if limit > 0:
            query = query.limit(limit)
        tickers = [row[0] for row in self.session.execute(query).all()]
        summaries: list[RefreshSummary] = []
        for ticker in tickers:
            try:
                summaries.append(
                    self.refresh_ticker(ticker, force=force, max_filings=max_filings)
                )
            except Exception as exc:  # pragma: no cover - defensive for scheduler loop
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
        return summaries


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
