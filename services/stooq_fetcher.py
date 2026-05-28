"""Stooq nightly price downloader and extractor."""

from __future__ import annotations

import io
import logging
import zipfile
from typing import Any

import httpx
import pandas as pd

LOGGER = logging.getLogger(__name__)

STOOQ_US_ZIP_URL = "https://stooq.com/db/h/us_txt.zip"


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
