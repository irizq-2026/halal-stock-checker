"""Market-cap calculation and storage service."""

from __future__ import annotations

import logging
from typing import Any, Protocol

LOGGER = logging.getLogger(__name__)


class DbConnProtocol(Protocol):
    async def fetch(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...
    async def execute(self, query: str, params: dict[str, Any] | None = None) -> None: ...


async def calculate_and_store_market_caps(
    db_conn: DbConnProtocol,
    prices: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Joins prices with sec_shares from DB.
    Calculates market_cap = close_price * shares_outstanding.
    Upserts into stock_prices table.
    Returns summary dict.
    """
    share_rows = await db_conn.fetch(
        "SELECT ticker, shares_outstanding FROM sec_shares",
    )
    shares_map = {
        str(row["ticker"]).upper().strip(): row.get("shares_outstanding")
        for row in share_rows
    }

    success = 0
    no_shares = 0
    latest_price_date = None

    for ticker, price_data in prices.items():
        close_price = float(price_data["close"])
        price_date = price_data["date"]
        latest_price_date = price_date
        shares = shares_map.get(ticker)
        if shares and int(shares) > 0:
            shares_int = int(shares)
            market_cap = round(close_price * shares_int, 2)
        else:
            shares_int = None
            market_cap = None
            no_shares += 1

        await db_conn.execute(
            """
            INSERT INTO stock_prices (
                ticker,
                close_price,
                price_date,
                shares_outstanding,
                market_cap,
                updated_at
            )
            VALUES (
                :ticker,
                :close_price,
                :price_date,
                :shares_outstanding,
                :market_cap,
                NOW()
            )
            ON CONFLICT (ticker, price_date)
            DO UPDATE SET
                close_price = EXCLUDED.close_price,
                shares_outstanding = EXCLUDED.shares_outstanding,
                market_cap = EXCLUDED.market_cap,
                updated_at = NOW()
            """,
            {
                "ticker": ticker,
                "close_price": close_price,
                "price_date": price_date,
                "shares_outstanding": shares_int,
                "market_cap": market_cap,
            },
        )
        success += 1

    summary = {
        "total_tickers": len(prices),
        "stored": success,
        "missing_shares": no_shares,
        "date": str(latest_price_date) if latest_price_date else None,
    }
    LOGGER.info("Market cap calculation summary: %s", summary)
    return summary
