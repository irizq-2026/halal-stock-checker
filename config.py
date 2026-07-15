"""Configuration helpers for SEC-backed data pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _normalize_database_url(raw: str | None) -> str:
    value = (raw or "").strip().strip("'\"")
    if value.startswith("postgres://"):
        return "postgresql+psycopg2://" + value[len("postgres://") :]
    return value


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
    database_url: str = _normalize_database_url(
        os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg2://postgres:postgres@localhost:5432/halal_stocks",
        )
    )
    sec_user_agent: str = os.getenv(
        "SEC_USER_AGENT",
        "iRizq Stock Checker salam@iRizq.com",
    )
    sec_timeout_seconds: float = _env_float("SEC_TIMEOUT_SECONDS", 20.0)
    sec_rate_limit_per_second: float = _env_float("SEC_RATE_LIMIT_PER_SECOND", 10.0)
    sec_max_retries: int = _env_int("SEC_MAX_RETRIES", 4)
    fmp_api_key: str = os.getenv("FMP_API_KEY", "")
    fmp_base_url: str = os.getenv("FMP_BASE_URL", "https://financialmodelingprep.com/api")
    fmp_timeout_seconds: float = _env_float("FMP_TIMEOUT_SECONDS", 15.0)
    refresh_cron_day_of_week: str = os.getenv("REFRESH_CRON_DAY_OF_WEEK", "sun")
    refresh_cron_hour_utc: int = _env_int("REFRESH_CRON_HOUR_UTC", 3)
    refresh_cron_minute_utc: int = _env_int("REFRESH_CRON_MINUTE_UTC", 0)
    refresh_max_filings_per_company: int = _env_int("REFRESH_MAX_FILINGS_PER_COMPANY", 8)
    refresh_default_limit: int = _env_int("REFRESH_DEFAULT_LIMIT", 0)
    admin_api_token: str = os.getenv("ADMIN_API_TOKEN", "")
    analytics_admin_password: str = os.getenv("ANALYTICS_ADMIN_PASSWORD", "change-me")
    analytics_session_secret: str = os.getenv("ANALYTICS_SESSION_SECRET", "change-me-session-secret")
    analytics_cookie_name: str = os.getenv("ANALYTICS_COOKIE_NAME", "uid")
    analytics_cookie_max_age_seconds: int = _env_int("ANALYTICS_COOKIE_MAX_AGE_SECONDS", 31_536_000)
    analytics_cache_ttl_seconds: int = _env_int("ANALYTICS_CACHE_TTL_SECONDS", 30)
    analytics_sslmode: str = os.getenv("ANALYTICS_SSLMODE", "require")


settings = Settings()
