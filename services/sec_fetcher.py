"""SEC EDGAR shares-outstanding fetcher."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

import httpx

LOGGER = logging.getLogger(__name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

SEC_HEADERS_BASE = {
    "User-Agent": "iRizq.com admin@irizq.com",
    "Accept-Encoding": "gzip, deflate",
}
SEC_HEADERS_FACTS = {
    **SEC_HEADERS_BASE,
    "Host": "data.sec.gov",
}

SHARES_TAG_PRIORITY = (
    ("us-gaap", "CommonStockSharesOutstanding"),
    ("us-gaap", "SharesOutstanding"),
    ("dei", "EntityCommonStockSharesOutstanding"),
)
VALID_FORMS = {"10-K", "10-Q"}


class DbConnProtocol(Protocol):
    async def execute(self, query: str, params: dict[str, Any] | None = None) -> None: ...


@dataclass
class SharesRecord:
    ticker: str
    cik: str
    company_name: str
    shares_outstanding: int | None
    shares_date: date | None


def _pad_cik(cik: str | int) -> str:
    return str(cik).strip().zfill(10)


def _parse_date(raw: Any) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), "%Y-%m-%d").date()
    except ValueError:
        return None


def _extract_latest_shares(company_facts: dict[str, Any]) -> tuple[int | None, date | None]:
    facts = company_facts.get("facts") or {}
    for taxonomy, tag in SHARES_TAG_PRIORITY:
        tagged = (((facts.get(taxonomy) or {}).get(tag) or {}).get("units") or {}).get("shares") or []
        if not isinstance(tagged, list):
            continue
        filtered_rows = []
        for row in tagged:
            form = str((row or {}).get("form") or "").upper().strip()
            if form not in VALID_FORMS:
                continue
            shares_val = (row or {}).get("val")
            try:
                shares_int = int(shares_val)
            except (TypeError, ValueError):
                continue
            end_date = _parse_date((row or {}).get("end"))
            if not end_date:
                continue
            filtered_rows.append((end_date, shares_int))
        if not filtered_rows:
            continue
        filtered_rows.sort(key=lambda item: item[0], reverse=True)
        latest_date, latest_value = filtered_rows[0]
        return latest_value, latest_date
    return None, None


async def fetch_company_ticker_map(client: httpx.AsyncClient) -> dict[str, dict[str, str]]:
    response = await client.get(SEC_TICKERS_URL, headers=SEC_HEADERS_BASE)
    response.raise_for_status()
    payload = response.json()
    mapping: dict[str, dict[str, str]] = {}
    for _, row in payload.items():
        ticker = str((row or {}).get("ticker") or "").upper().strip()
        if not ticker:
            continue
        cik_str = str((row or {}).get("cik_str") or "").strip()
        if not cik_str:
            continue
        mapping[ticker] = {
            "cik": _pad_cik(cik_str),
            "company_name": str((row or {}).get("title") or ticker).strip(),
        }
    return mapping


async def _fetch_company_facts(client: httpx.AsyncClient, ticker: str, cik: str) -> dict[str, Any] | None:
    url = SEC_COMPANY_FACTS_URL.format(cik=_pad_cik(cik))
    response = await client.get(url, headers=SEC_HEADERS_FACTS)
    if response.status_code == 429:
        LOGGER.error("SEC rate limited for %s — waiting 60s then retrying once", ticker)
        await asyncio.sleep(60)
        retry_response = await client.get(url, headers=SEC_HEADERS_FACTS)
        if retry_response.status_code == 429:
            LOGGER.error("SEC rate limited for %s — skipped", ticker)
            return None
        retry_response.raise_for_status()
        return retry_response.json()
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


async def _upsert_sec_shares(db_conn: DbConnProtocol, record: SharesRecord) -> None:
    await db_conn.execute(
        """
        INSERT INTO sec_shares (
            ticker,
            cik,
            company_name,
            shares_outstanding,
            shares_date,
            fetched_at
        )
        VALUES (
            :ticker,
            :cik,
            :company_name,
            :shares_outstanding,
            :shares_date,
            NOW()
        )
        ON CONFLICT (ticker)
        DO UPDATE SET
            shares_outstanding = EXCLUDED.shares_outstanding,
            shares_date = EXCLUDED.shares_date,
            fetched_at = NOW()
        """,
        {
            "ticker": record.ticker,
            "cik": record.cik,
            "company_name": record.company_name,
            "shares_outstanding": record.shares_outstanding,
            "shares_date": record.shares_date,
        },
    )


async def fetch_and_store_sec_shares(
    db_conn: DbConnProtocol,
    *,
    limit: int | None = None,
) -> dict[str, int]:
    """
    Fetches shares_outstanding for all US stocks from SEC EDGAR.
    Upserts results into sec_shares table.
    Returns summary: {"processed": 500, "success": 480, "failed": 20}
    """
    processed = 0
    success = 0
    failed = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        ticker_map = await fetch_company_ticker_map(client)
        ticker_items = sorted(ticker_map.items(), key=lambda item: item[0])
        if limit and limit > 0:
            ticker_items = ticker_items[:limit]

        for offset in range(0, len(ticker_items), 50):
            batch = ticker_items[offset : offset + 50]
            for ticker, meta in batch:
                processed += 1
                cik = meta["cik"]
                company_name = meta["company_name"]
                try:
                    company_facts = await _fetch_company_facts(client, ticker, cik)
                    await asyncio.sleep(0.15)
                    if not company_facts:
                        failed += 1
                        continue
                    shares_outstanding, shares_date = _extract_latest_shares(company_facts)
                    if shares_outstanding is None:
                        LOGGER.info("No shares data found for %s", ticker)
                        failed += 1
                        continue
                    record = SharesRecord(
                        ticker=ticker,
                        cik=cik,
                        company_name=company_name,
                        shares_outstanding=shares_outstanding,
                        shares_date=shares_date,
                    )
                    await _upsert_sec_shares(db_conn, record)
                    success += 1
                except Exception:
                    LOGGER.exception("Failed SEC shares fetch for %s", ticker)
                    failed += 1
            LOGGER.info("Processed %s/%s tickers...", min(offset + 50, len(ticker_items)), len(ticker_items))

    return {
        "processed": processed,
        "success": success,
        "failed": failed,
    }
