"""Scheduled cache maintenance: SEC shares refresh + lazy price mode."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from db import SessionLocal
from services.sec_fetcher import fetch_and_store_sec_shares

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DbConnection:
    """Async adapter over the project's sync SQLAlchemy session."""

    def __init__(self) -> None:
        self._session = SessionLocal()

    async def fetch(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._fetch_sync, query, params or {})

    async def fetchrow(self, query: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._fetchrow_sync, query, params or {})

    async def execute(self, query: str, params: dict[str, Any] | None = None) -> None:
        await asyncio.to_thread(self._execute_sync, query, params or {})

    async def close(self) -> None:
        await asyncio.to_thread(self._session.close)

    def _fetch_sync(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        result = self._session.execute(text(query), params).mappings().all()
        return [dict(row) for row in result]

    def _fetchrow_sync(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        result = self._session.execute(text(query), params).mappings().first()
        return dict(result) if result else None

    def _execute_sync(self, query: str, params: dict[str, Any]) -> None:
        try:
            self._session.execute(text(query), params)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise


async def get_db_connection() -> DbConnection:
    """Connect using existing project SQLAlchemy session factory."""
    conn = DbConnection()
    try:
        await conn.fetch("SELECT 1")
    except Exception:
        await conn.close()
        raise
    return conn


def _migration_sql_path() -> Path:
    return ROOT_DIR / "db" / "migrations" / "create_stock_prices.sql"


async def create_tables_if_not_exist(db_conn: DbConnection) -> None:
    migration_path = _migration_sql_path()
    sql_content = migration_path.read_text(encoding="utf-8")
    statements = [chunk.strip() for chunk in sql_content.split(";") if chunk.strip()]
    for statement in statements:
        await db_conn.execute(statement)


async def run_nightly_update() -> dict[str, Any]:
    start = datetime.now()
    logger.info("=== Nightly price update started: %s ===", start.isoformat())

    db_conn: DbConnection | None = None
    try:
        db_conn = await get_db_connection()

        logger.info("Ensuring database tables exist...")
        await create_tables_if_not_exist(db_conn)

        if datetime.now().weekday() == 6:
            logger.info("Sunday — refreshing SEC shares data...")
            sec_result = await fetch_and_store_sec_shares(db_conn)
            logger.info("SEC shares result: %s", sec_result)
        else:
            logger.info("Skipping SEC refresh (not Sunday)")

        logger.info("Bulk price fetch disabled; prices refresh lazily per ticker via yfinance cache-aside.")

        end = datetime.now()
        duration = int((end - start).total_seconds())
        logger.info("=== Nightly update complete in %ss ===", duration)
        return {
            "status": "success",
            "duration_seconds": duration,
            "price_mode": "lazy-per-ticker-yfinance",
            "stored": 0,
        }

    except Exception as exc:
        logger.error("Nightly update FAILED: %s", exc, exc_info=True)
        return {"status": "failed", "error": str(exc)}

    finally:
        if db_conn:
            await db_conn.close()


if __name__ == "__main__":
    output = asyncio.run(run_nightly_update())
    if output.get("status") != "success":
        raise SystemExit(1)
