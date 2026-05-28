"""FastAPI endpoints for local cached screening results and refresh control."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from config import settings
from db import SessionLocal
from logging_setup import configure_logging
from scheduler import start_scheduler
from sec_refresh import latest_cached_screen_row, refresh_single_ticker, weekly_sec_refresh

configure_logging()

app = FastAPI(title="Halal Stock Checker API", version="1.0.0")


class RefreshRequest(BaseModel):
    ticker: str | None = Field(default=None, description="Optional single ticker to refresh.")
    force: bool = False
    limit: int = 0


def _validate_admin_token(token: str | None) -> None:
    expected = settings.admin_api_token
    if not expected:
        return
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token.",
        )


def _admin_guard(x_admin_token: str | None = Header(default=None)) -> None:
    _validate_admin_token(x_admin_token)


@app.on_event("startup")
def _startup() -> None:
    if settings.refresh_default_limit >= 0:
        start_scheduler()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"}


@app.get("/api/v1/screen/{ticker}")
def get_cached_screen(ticker: str) -> dict[str, Any]:
    session = SessionLocal()
    try:
        row = latest_cached_screen_row(session, ticker)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticker not found in local cache. Ask admin to refresh.",
            )
        company, filing, normalized, result = row
        return {
            "ticker": company.ticker,
            "company_name": company.company_name,
            "exchange": company.exchange,
            "sector": company.sector,
            "industry": company.industry,
            "filing": {
                "accession_number": filing.accession_number,
                "filing_type": filing.filing_type,
                "filing_date": str(filing.filing_date),
            },
            "financials": {
                "total_revenue": float(normalized.total_revenue) if normalized.total_revenue is not None else None,
                "interest_income": float(normalized.interest_income) if normalized.interest_income is not None else None,
                "total_debt": float(normalized.total_debt) if normalized.total_debt is not None else None,
                "cash_and_equivalents": float(normalized.cash_and_equivalents) if normalized.cash_and_equivalents is not None else None,
                "total_assets": float(normalized.total_assets) if normalized.total_assets is not None else None,
                "market_cap": float(normalized.market_cap) if normalized.market_cap is not None else None,
                "operating_income": float(normalized.operating_income) if normalized.operating_income is not None else None,
                "net_income": float(normalized.net_income) if normalized.net_income is not None else None,
                "shares_outstanding": float(normalized.shares_outstanding) if normalized.shares_outstanding is not None else None,
                "mapped_tags": normalized.source_metadata_json,
            },
            "screen_result": {
                "debt_ratio": float(result.debt_ratio) if result.debt_ratio is not None else None,
                "interest_income_ratio": float(result.interest_income_ratio) if result.interest_income_ratio is not None else None,
                "cash_ratio": float(result.cash_ratio) if result.cash_ratio is not None else None,
                "halal_status": result.halal_status,
                "reasoning_json": result.reasoning_json,
            },
            "data_source": {
                "name": result.data_source,
                "filing_date": str(result.source_filing_date) if result.source_filing_date else None,
                "last_updated": result.last_updated.isoformat() if result.last_updated else None,
            },
        }
    finally:
        session.close()


@app.post("/api/v1/admin/refresh", dependencies=[Depends(_admin_guard)])
def trigger_refresh(body: RefreshRequest) -> dict[str, Any]:
    if body.ticker:
        summary = refresh_single_ticker(
            body.ticker,
            force=body.force,
            max_filings=settings.refresh_max_filings_per_company,
        )
        return {"mode": "single", "summary": summary.__dict__}

    summaries = weekly_sec_refresh(
        limit=max(body.limit, 0),
        force=body.force,
        max_filings=settings.refresh_max_filings_per_company,
    )
    return {
        "mode": "batch",
        "count": len(summaries),
        "summaries": [summary.__dict__ for summary in summaries],
    }
