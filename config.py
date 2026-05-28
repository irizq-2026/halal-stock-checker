"""Configuration helpers for SEC-backed data pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/halal_stocks",
    )
    sec_user_agent: str = os.getenv(
        "SEC_USER_AGENT",
        "HalalStockChecker support@example.com",
    )
    sec_timeout_seconds: float = _env_float("SEC_TIMEOUT_SECONDS", 20.0)
    sec_rate_limit_per_second: float = _env_float("SEC_RATE_LIMIT_PER_SECOND", 5.0)
    sec_max_retries: int = _env_int("SEC_MAX_RETRIES", 4)
    refresh_cron_day_of_week: str = os.getenv("REFRESH_CRON_DAY_OF_WEEK", "sun")
    refresh_cron_hour_utc: int = _env_int("REFRESH_CRON_HOUR_UTC", 3)
    refresh_cron_minute_utc: int = _env_int("REFRESH_CRON_MINUTE_UTC", 0)
    refresh_max_filings_per_company: int = _env_int("REFRESH_MAX_FILINGS_PER_COMPANY", 8)
    refresh_default_limit: int = _env_int("REFRESH_DEFAULT_LIMIT", 0)
    admin_api_token: str = os.getenv("ADMIN_API_TOKEN", "")


settings = Settings()
