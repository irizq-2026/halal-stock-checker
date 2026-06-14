"""Live ethical insights resolver for supported watchlist tickers."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)

OFFICIAL_BDS_URL = "https://bdsmovement.net/Guide-to-BDS-Boycott"
AFSC_AUTOCOMPLETE_URL = (
    "https://investigate.afsc.org/search_api_autocomplete/afsc_company_search"
    "?display=page_1&&filter=key"
)
UN_OHCHR_NAMES_URL = "https://data.opensanctions.org/datasets/latest/ps_ohchr_settlement/names.txt"
WHO_PROFITS_SEARCH_URL = "https://www.whoprofits.org/companies/find"

HTTP_TIMEOUT_SECONDS = 30
MAX_QUERY_VARIANTS = 6

_CORP_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "plc",
    "sa",
    "ag",
    "group",
    "holdings",
}

_MANUAL_ALIASES: dict[str, tuple[str, ...]] = {
    "AAPL": ("Apple", "Apple Inc"),
    "AMZN": ("Amazon", "Amazon.com", "Amazon.com Inc"),
    "CRCL": ("Circle", "Circle Internet Group"),
    "GOOG": ("Google", "Alphabet"),
    "GOOGL": ("Google", "Alphabet"),
    "JPM": ("JPMorgan", "JPMorgan Chase", "JP Morgan"),
    "MSFT": ("Microsoft", "Microsoft Corp", "Microsoft Corporation"),
    "PLTR": ("Palantir", "Palantir Technologies"),
    "QS": ("QuantumScape",),
    "SPCX": ("SpaceX",),
    "TSLA": ("Tesla", "Tesla Inc"),
    "XOM": ("Exxon", "Exxon Mobil"),
}

_SPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")


def _normalize(value: str) -> str:
    lowered = html.unescape(value or "").lower().replace("&", " and ")
    lowered = _NON_ALNUM_RE.sub(" ", lowered)
    lowered = _SPACE_RE.sub(" ", lowered).strip()
    return lowered


def _clean_html_text(raw: str) -> str:
    without_tags = _TAG_RE.sub(" ", raw or "")
    return _SPACE_RE.sub(" ", html.unescape(without_tags)).strip()


def _trim_corporate_suffixes(name: str) -> str:
    parts = _normalize(name).split()
    while parts and parts[-1] in _CORP_SUFFIXES:
        parts.pop()
    return " ".join(parts)


def _query_variants(ticker: str, company_name: str) -> list[str]:
    aliases = {_normalize(company_name), _trim_corporate_suffixes(company_name), ticker.lower().strip()}
    aliases.update(_normalize(alias) for alias in _MANUAL_ALIASES.get(ticker.upper(), ()))
    aliases = {alias for alias in aliases if len(alias) >= 2}
    ranked = sorted(aliases, key=lambda value: (-len(value), value))
    return ranked[:MAX_QUERY_VARIANTS]


def _is_probable_match(source_name: str, aliases: list[str]) -> bool:
    normalized_source = _normalize(source_name)
    if not normalized_source:
        return False
    for alias in aliases:
        normalized_alias = _normalize(alias)
        if len(normalized_alias) < 3:
            continue
        alias_pattern = rf"\b{re.escape(normalized_alias)}\b"
        source_pattern = rf"\b{re.escape(normalized_source)}\b"
        if re.search(alias_pattern, normalized_source) or re.search(source_pattern, normalized_alias):
            return True
    return False


def _fetch_official_bds_targets(session: requests.Session) -> list[str]:
    response = session.get(OFFICIAL_BDS_URL, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    matches = re.findall(
        r"<button[^>]*accordion-button[^>]*>(.*?)</button>",
        response.text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return [_clean_html_text(match) for match in matches if _clean_html_text(match)]


def _fetch_afsc_candidates(session: requests.Session, queries: list[str]) -> list[str]:
    found: list[str] = []
    for query in queries:
        response = session.get(
            AFSC_AUTOCOMPLETE_URL,
            params={"q": query},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict):
                continue
            value = str(item.get("value", "")).strip()
            if value:
                found.append(value)
    return sorted(set(found))


def _fetch_un_ohchr_names(session: requests.Session) -> list[str]:
    response = session.get(UN_OHCHR_NAMES_URL, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    lines = [line.strip() for line in response.text.splitlines() if line.strip()]
    return lines


def _fetch_who_profits_candidates(session: requests.Session, queries: list[str]) -> list[str]:
    found: list[str] = []
    for query in queries:
        response = session.get(
            WHO_PROFITS_SEARCH_URL,
            params={"Name": query, "Type": "List"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw_titles = re.findall(
            r"<h4[^>]*>(.*?)</h4>",
            response.text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for title in raw_titles:
            cleaned = _clean_html_text(title)
            cleaned = re.sub(r"^\d+\s*-\s*", "", cleaned).strip()
            if cleaned:
                found.append(cleaned)
    return sorted(set(found))


def resolve_ethical_insights(ticker: str, company_name: str) -> dict[str, Any]:
    """Resolve ethical source flags from live public datasets/pages."""
    normalized_ticker = (ticker or "").strip().upper()
    normalized_company = (company_name or "").strip()
    if not normalized_ticker or not normalized_company:
        raise ValueError("Ticker and company_name are required.")

    query_aliases = _query_variants(normalized_ticker, normalized_company)
    if not query_aliases:
        raise ValueError(f"No usable aliases for {normalized_ticker}.")

    source_matches: dict[str, list[str]] = {
        "official_bds": [],
        "afsc": [],
        "un_ohchr": [],
        "who_profits": [],
    }

    with requests.Session() as session:
        session.headers.update(
            {
                "User-Agent": "iRizq Ethical Insights Refresh/1.0 (public-source-ingest)",
                "Accept": "application/json, text/plain, */*",
            }
        )

        bds_targets = _fetch_official_bds_targets(session)
        source_matches["official_bds"] = [
            entry for entry in bds_targets if _is_probable_match(entry, query_aliases)
        ]

        afsc_candidates = _fetch_afsc_candidates(session, query_aliases)
        source_matches["afsc"] = [
            entry for entry in afsc_candidates if _is_probable_match(entry, query_aliases)
        ]

        ohchr_names = _fetch_un_ohchr_names(session)
        source_matches["un_ohchr"] = [
            entry for entry in ohchr_names if _is_probable_match(entry, query_aliases)
        ]

        who_profits_candidates = _fetch_who_profits_candidates(session, query_aliases)
        source_matches["who_profits"] = [
            entry
            for entry in who_profits_candidates
            if _is_probable_match(entry, query_aliases)
        ]

    refreshed_at = datetime.now(timezone.utc).isoformat()
    result = {
        "official_bds": bool(source_matches["official_bds"]),
        "afsc": bool(source_matches["afsc"]),
        "un_ohchr": bool(source_matches["un_ohchr"]),
        "who_profits": bool(source_matches["who_profits"]),
        "sources_reviewed": 4,
        "refresh_metadata": {
            "refreshed_at": refreshed_at,
            "ticker": normalized_ticker,
            "company_name": normalized_company,
            "source_urls": {
                "official_bds": OFFICIAL_BDS_URL,
                "afsc": AFSC_AUTOCOMPLETE_URL,
                "un_ohchr": UN_OHCHR_NAMES_URL,
                "who_profits": WHO_PROFITS_SEARCH_URL,
            },
            "matches": source_matches,
            "query_aliases": query_aliases,
        },
    }
    LOGGER.info("Resolved ethical insights for %s: %s", normalized_ticker, result)
    return result
