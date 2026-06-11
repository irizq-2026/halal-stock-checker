"""Stooq nightly price downloader and extractor."""

from __future__ import annotations

import io
import logging
import csv
import asyncio
import zipfile
from typing import Any

import httpx
import pandas as pd

LOGGER = logging.getLogger(__name__)

STOOQ_US_ZIP_URL = "https://stooq.com/db/h/us_txt.zip"
STOOQ_QUOTE_URL = "https://stooq.com/q/l/"


async def download_stooq_zip() -> io.BytesIO:
    """Download Stooq US historical zip payload."""
    LOGGER.info("Downloading stooq zip from %s", STOOQ_US_ZIP_URL)
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(STOOQ_US_ZIP_URL, headers=headers, follow_redirects=True)
            response.raise_for_status()
    except Exception:
        LOGGER.error("Failed to download stooq zip", exc_info=True)
        raise
    payload = response.content
    LOGGER.info("Stooq zip download complete, bytes=%s", len(payload))
    return io.BytesIO(payload)


def _parse_stooq_date_column(df: pd.DataFrame) -> pd.Series:
    raw = df["date"].astype(str).str.strip()
    parsed = pd.to_datetime(raw, format="%Y%m%d", errors="coerce")
    if parsed.notna().any():
        return parsed
    return pd.to_datetime(raw, errors="coerce")


async def extract_latest_prices(zip_bytes: io.BytesIO) -> dict[str, dict[str, Any]]:
    """
    Returns dict: {ticker: {"close": float, "date": date}}
    Only returns the MOST RECENT row per ticker.
    """
    prices: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(zip_bytes, "r") as zip_file:
        for filename in zip_file.namelist():
            lower_name = filename.lower()
            if "daily/us" not in lower_name:
                continue
            if not lower_name.endswith(".txt"):
                continue

            basename = filename.split("/")[-1]
            ticker = basename.split(".")[0].upper().strip()
            if not ticker:
                continue

            try:
                with zip_file.open(filename) as file_handle:
                    df = pd.read_csv(file_handle)
                if df.empty:
                    continue
                df.columns = [str(col).strip().lower() for col in df.columns]
                if "date" not in df.columns or "close" not in df.columns:
                    LOGGER.error("Stooq file missing required columns: %s", filename)
                    continue
                df["date"] = _parse_stooq_date_column(df)
                df = df.dropna(subset=["date"])
                if df.empty:
                    continue
                df = df.sort_values("date", ascending=False)
                latest = df.iloc[0]
                close_value = float(latest["close"])
                prices[ticker] = {
                    "close": close_value,
                    "date": latest["date"].date(),
                }
            except Exception:
                LOGGER.error("Failed to process stooq file: %s", filename, exc_info=True)
                continue

    if not prices:
        return {}

    latest_date = max(entry["date"] for entry in prices.values())
    filtered_prices = {
        ticker: payload
        for ticker, payload in prices.items()
        if payload["date"] == latest_date
    }
    LOGGER.info("Latest trading date from stooq: %s", latest_date)
    LOGGER.info("Total tickers with prices: %s", len(filtered_prices))
    return filtered_prices


def _parse_quote_row_csv(payload: str) -> tuple[float, Any] | None:
    text = (payload or "").strip()
    if not text:
        return None
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return None

    # Prefer header-form response from f=sd2t2ohlcv
    if len(rows) >= 2 and rows[0] and rows[0][0].strip().lower() == "symbol":
        data = rows[1]
        if len(data) < 7:
            return None
        date_raw = data[1].strip()
        close_raw = data[6].strip()
        if date_raw in {"N/D", ""} or close_raw in {"N/D", ""}:
            return None
        date_value = pd.to_datetime(date_raw, format="%Y-%m-%d", errors="coerce")
        if pd.isna(date_value):
            date_value = pd.to_datetime(date_raw, format="%Y%m%d", errors="coerce")
        if pd.isna(date_value):
            return None
        return float(close_raw), date_value.date()

    # Fallback: single-line no-header format
    data = rows[0]
    if len(data) < 7:
        return None
    date_raw = data[1].strip()
    close_raw = data[6].strip()
    if date_raw in {"N/D", ""} or close_raw in {"N/D", ""}:
        return None
    date_value = pd.to_datetime(date_raw, format="%Y%m%d", errors="coerce")
    if pd.isna(date_value):
        date_value = pd.to_datetime(date_raw, format="%Y-%m-%d", errors="coerce")
    if pd.isna(date_value):
        return None
    return float(close_raw), date_value.date()


async def fetch_latest_prices_for_tickers(
    tickers: list[str],
    *,
    concurrency: int = 15,
    batch_size: int = 200,
) -> dict[str, dict[str, Any]]:
    """
    Fallback path when bulk zip download is unavailable:
    fetch latest close per ticker from stooq quote endpoint.
    """
    if not tickers:
        return {}

    headers = {"User-Agent": "Mozilla/5.0"}
    prices: dict[str, dict[str, Any]] = {}
    sem = asyncio.Semaphore(max(concurrency, 1))

    async def _fetch_one(client: httpx.AsyncClient, ticker: str) -> tuple[str, dict[str, Any] | None]:
        stooq_symbol = f"{ticker.lower()}.us"
        params = {"s": stooq_symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"}
        async with sem:
            response = await client.get(STOOQ_QUOTE_URL, params=params, headers=headers)
            response.raise_for_status()
            parsed = _parse_quote_row_csv(response.text)
            await asyncio.sleep(0.05)
        if not parsed:
            return ticker, None
        close_value, date_value = parsed
        return ticker, {"close": close_value, "date": date_value}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for offset in range(0, len(tickers), batch_size):
            batch = tickers[offset : offset + batch_size]
            results = await asyncio.gather(*(_fetch_one(client, ticker) for ticker in batch), return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    LOGGER.error("Failed stooq quote fetch in batch", exc_info=True)
                    continue
                ticker, payload = result
                if payload:
                    prices[ticker] = payload
            LOGGER.info(
                "Processed stooq quote batch: %s/%s tickers",
                min(offset + batch_size, len(tickers)),
                len(tickers),
            )

    if not prices:
        return {}
    latest_date = max(entry["date"] for entry in prices.values())
    filtered = {
        ticker: payload
        for ticker, payload in prices.items()
        if payload["date"] == latest_date
    }
    LOGGER.info("Latest trading date from stooq quote API: %s", latest_date)
    LOGGER.info("Total tickers with fallback prices: %s", len(filtered))
    return filtered
