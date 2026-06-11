"""FastAPI endpoints for local cached screening results and refresh control."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Form, Header, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from analytics import ensure_events_table, get_dashboard_metrics, infer_source, track_event
from config import settings
from db import SessionLocal
from jobs.nightly_price_update import get_db_connection, run_nightly_update
from logging_setup import configure_logging
from scheduler import start_scheduler
from sec_refresh import latest_cached_screen_row, refresh_single_ticker, weekly_sec_refresh
from services.yfinance_price_cache import get_cached_or_refresh_price_row

configure_logging()
LOGGER = logging.getLogger(__name__)

app = FastAPI(title="Halal Stock Checker API", version="1.0.0")
app.add_middleware(SessionMiddleware, secret_key=settings.analytics_session_secret)
templates = Jinja2Templates(directory="templates")
jobs_router = APIRouter(prefix="/jobs", tags=["jobs"])
CRON_SECRET = os.getenv("CRON_SECRET", "change-me-in-production")


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
    try:
        ensure_events_table()
    except Exception:  # pragma: no cover - startup resilience
        LOGGER.exception("Analytics table initialization failed.")
    if settings.refresh_default_limit >= 0:
        start_scheduler()


def _resolve_uid(request: Request, response: Response) -> str:
    cookie_name = settings.analytics_cookie_name
    user_id = (request.cookies.get(cookie_name) or "").strip()
    if user_id:
        return user_id
    user_id = str(uuid.uuid4())
    response.set_cookie(
        key=cookie_name,
        value=user_id,
        max_age=max(settings.analytics_cookie_max_age_seconds, 3600),
        httponly=True,
        samesite="lax",
    )
    return user_id


def _safe_track(*, event_type: str, user_id: str, ticker: str | None, source: str) -> None:
    try:
        track_event(event_type=event_type, user_id=user_id, ticker=ticker, source=source)
    except Exception:  # pragma: no cover - analytics must not break core flows
        LOGGER.exception("Failed to track analytics event %s for user %s", event_type, user_id)


@app.get("/", response_class=HTMLResponse)
def root(request: Request) -> HTMLResponse:
    html_response = HTMLResponse(
        "<html><body><h3>Halal Stock Checker API</h3><p>Use /health or /api/v1/screen/{ticker}.</p></body></html>"
    )
    user_id = _resolve_uid(request, html_response)
    source = infer_source(request.query_params.get("utm_source"), request.headers.get("referer"))
    _safe_track(event_type="visit", user_id=user_id, ticker=None, source=source)
    return html_response


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"}


@app.get("/api/v1/screen/{ticker}")
def get_cached_screen(ticker: str, request: Request, response: Response) -> dict[str, Any]:
    user_id = _resolve_uid(request, response)
    source = infer_source(request.query_params.get("utm_source"), request.headers.get("referer"))
    _safe_track(
        event_type="search",
        user_id=user_id,
        ticker=ticker.upper().strip(),
        source=source,
    )
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


@app.get("/admin-login", response_class=HTMLResponse)
def admin_login_page(request: Request) -> HTMLResponse:
    if request.session.get("admin_authenticated"):
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={"error": None},
    )


@app.post("/admin-login", response_class=HTMLResponse)
def admin_login_submit(request: Request, password: str = Form(...)) -> HTMLResponse:
    if password != settings.analytics_admin_password:
        return templates.TemplateResponse(
            request=request,
            name="admin_login.html",
            context={"error": "Invalid password."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    request.session["admin_authenticated"] = True
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin-logout")
def admin_logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/admin-login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request) -> HTMLResponse:
    if not request.session.get("admin_authenticated"):
        return RedirectResponse(url="/admin-login", status_code=status.HTTP_303_SEE_OTHER)
    error: str | None = None
    try:
        stats_payload = get_dashboard_metrics()
    except Exception:  # pragma: no cover - dashboard resilience
        LOGGER.exception("Failed to load dashboard analytics.")
        stats_payload = {
            "total_visits": 0,
            "total_searches": 0,
            "unique_users": 0,
            "return_users": 0,
            "top_tickers": [],
            "traffic_sources": [],
            "conversion_rate": 0.0,
            "last_events": [],
        }
        error = "Analytics database is temporarily unavailable."
    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={
            "stats": stats_payload,
            "conversion_rate_pct": f"{stats_payload['conversion_rate'] * 100:.2f}%",
            "error": error,
        },
    )


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


@jobs_router.post("/nightly-update")
async def trigger_nightly_update(x_cron_secret: str | None = Header(default=None)) -> dict[str, Any]:
    """
    Triggers the nightly price update job.
    Protected by CRON_SECRET header.
    Called by Render cron job nightly.
    """
    if x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await run_nightly_update()


@jobs_router.get("/status")
async def job_status() -> dict[str, Any]:
    """
    Returns the most recent price update status.
    Shows latest price_date and ticker count in DB.
    """
    db_conn = await get_db_connection()
    try:
        latest = await db_conn.fetchrow(
            """
            SELECT MAX(price_date) AS latest_price_date
            FROM stock_prices
            """
        )
        latest_date = latest.get("latest_price_date") if latest else None
        ticker_count = 0
        if latest_date:
            count_row = await db_conn.fetchrow(
                """
                SELECT COUNT(*) AS ticker_count
                FROM stock_prices
                WHERE price_date = :latest_price_date
                """,
                {"latest_price_date": latest_date},
            )
            ticker_count = int((count_row or {}).get("ticker_count") or 0)
        return {
            "latest_price_date": str(latest_date) if latest_date else None,
            "ticker_count": ticker_count,
        }
    finally:
        await db_conn.close()


@jobs_router.get("/market-cap/{ticker}")
async def get_market_cap(ticker: str) -> dict[str, Any]:
    """
    Returns most recent market-cap inputs for a ticker.
    Uses DB-first cache with per-ticker yfinance refresh fallback.
    """
    normalized_ticker = ticker.upper().strip()
    row = await asyncio.to_thread(get_cached_or_refresh_price_row, normalized_ticker)
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No price data found for {normalized_ticker}",
        )
    return {
        "ticker": row["ticker"],
        "close_price": float(row["close_price"]) if row["close_price"] is not None else None,
        "price_date": str(row["price_date"]),
        "shares_outstanding": row["shares_outstanding"],
        "market_cap": float(row["market_cap"]) if row["market_cap"] is not None else None,
        "updated_at": str(row["updated_at"]),
    }


app.include_router(jobs_router)
