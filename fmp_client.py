"""Financial Modeling Prep client for market-cap fallback data."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from config import settings

LOGGER = logging.getLogger(__name__)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


class FmpClient:
    """FMP API wrapper for fetching market-cap fallback inputs."""

    def __init__(self) -> None:
        self.api_key = settings.fmp_api_key.strip()
        self.base_url = settings.fmp_base_url.rstrip("/")
        self.timeout = settings.fmp_timeout_seconds
        self.session = requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _get_json(self, path: str) -> Any:
        if not self.enabled:
            return None
        url = f"{self.base_url}{path}"
        params = {"apikey": self.api_key}
        delay = 0.5
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(delay)
                    delay *= 2
        if last_error:
            LOGGER.warning("FMP request failed for %s: %s", path, last_error)
        return None

    def resolve_market_cap(
        self,
        ticker: str,
        *,
        shares_hint: float | None = None,
    ) -> tuple[float | None, dict[str, Any]]:
        """Resolve latest market cap using FMP direct value or price*shares."""
        if not self.enabled:
            return None, {"source": "fmp", "status": "disabled", "reason": "FMP_API_KEY missing"}

        symbol = ticker.strip().upper()
        quote_payload = self._get_json(f"/v3/quote/{symbol}")
        quote = quote_payload[0] if isinstance(quote_payload, list) and quote_payload else {}
        if not isinstance(quote, dict):
            quote = {}

        price = _to_float(quote.get("price"))
        market_cap = _to_float(
            quote.get("marketCap")
            or quote.get("marketcap")
            or quote.get("mktCap")
        )
        quote_shares = _to_float(quote.get("sharesOutstanding") or quote.get("shares_outstanding"))
        if market_cap is not None and market_cap > 0:
            return market_cap, {
                "source": "fmp",
                "status": "ok",
                "method": "direct_market_cap",
                "price": price,
                "shares_outstanding": quote_shares,
            }

        profile_payload = self._get_json(f"/v3/profile/{symbol}")
        profile = profile_payload[0] if isinstance(profile_payload, list) and profile_payload else {}
        if not isinstance(profile, dict):
            profile = {}
        profile_market_cap = _to_float(
            profile.get("mktCap")
            or profile.get("marketCap")
            or profile.get("marketcap")
        )
        profile_shares = _to_float(profile.get("sharesOutstanding") or profile.get("shares_outstanding"))

        if profile_market_cap is not None and profile_market_cap > 0:
            return profile_market_cap, {
                "source": "fmp",
                "status": "ok",
                "method": "profile_market_cap",
                "price": price,
                "shares_outstanding": profile_shares or quote_shares,
            }

        shares = quote_shares or profile_shares or shares_hint
        if price is not None and shares is not None and price > 0 and shares > 0:
            return price * shares, {
                "source": "fmp",
                "status": "ok",
                "method": "price_x_shares",
                "price": price,
                "shares_outstanding": shares,
                "shares_source": (
                    "quote"
                    if quote_shares
                    else "profile"
                    if profile_shares
                    else "sec_shares_hint"
                ),
            }

        return None, {
            "source": "fmp",
            "status": "unavailable",
            "method": "none",
            "price": price,
            "shares_outstanding": shares,
            "reason": "No usable market cap and insufficient price/shares for fallback.",
        }
