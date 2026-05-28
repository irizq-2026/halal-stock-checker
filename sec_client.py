"""HTTP client for SEC APIs with retry and rate limiting."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

from config import settings

LOGGER = logging.getLogger(__name__)

SEC_TICKER_MAPPING_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


class RateLimiter:
    """Simple token-interval limiter for SEC request pacing."""

    def __init__(self, requests_per_second: float) -> None:
        self.interval = 1.0 / max(requests_per_second, 0.1)
        self._lock = threading.Lock()
        self._last_request_ts = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last_request_ts
            if delta < self.interval:
                time.sleep(self.interval - delta)
            self._last_request_ts = time.monotonic()


def normalize_cik(cik: str | int) -> str:
    return str(cik).strip().zfill(10)


class SecApiClient:
    """SEC API wrapper used by weekly ingestion jobs."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Host": "data.sec.gov",
            }
        )
        self._rate_limiter = RateLimiter(settings.sec_rate_limit_per_second)

    def _request_json(self, url: str) -> dict[str, Any]:
        delay = 0.8
        last_error: Exception | None = None
        for attempt in range(settings.sec_max_retries):
            try:
                self._rate_limiter.wait()
                response = self._session.get(url, timeout=settings.sec_timeout_seconds)
                if response.status_code == 404:
                    return {}
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                if attempt < settings.sec_max_retries - 1:
                    LOGGER.warning("SEC request failed (attempt %s/%s): %s", attempt + 1, settings.sec_max_retries, url)
                    time.sleep(delay)
                    delay = min(delay * 2, 10.0)
        if last_error:
            raise last_error
        return {}

    def fetch_ticker_mapping(self) -> dict[str, dict[str, str]]:
        payload = self._request_json(SEC_TICKER_MAPPING_URL)
        mapping: dict[str, dict[str, str]] = {}
        for _, row in payload.items():
            ticker = str(row.get("ticker", "")).upper().strip()
            if not ticker:
                continue
            mapping[ticker] = {
                "cik": normalize_cik(row.get("cik_str", "")),
                "company_name": str(row.get("title", "")).strip() or ticker,
            }
        return mapping

    def fetch_company_submissions(self, cik: str) -> dict[str, Any]:
        return self._request_json(SEC_SUBMISSIONS_URL.format(cik=normalize_cik(cik)))

    def fetch_company_facts(self, cik: str) -> dict[str, Any]:
        return self._request_json(SEC_COMPANY_FACTS_URL.format(cik=normalize_cik(cik)))
