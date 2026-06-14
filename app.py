"""Halal Stock Checker (iRizq.com) - Streamlit UI."""

from __future__ import annotations

import base64
import datetime
import html
import os
import time
import uuid
from datetime import date
from urllib.parse import quote, urlparse

import psycopg2
import pandas as pd
import streamlit as st
from psycopg2 import pool as psycopg2_pool
from psycopg2.extras import RealDictCursor
from streamlit_searchbox import st_searchbox

from analytics import ensure_events_table, infer_source, track_event
from config import settings
from data import (
    CachedDataNotReadyError,
    DatabaseUnavailableError,
    TransientDataError,
    fetch_company_enrichment as _fetch_company_enrichment,
    fetch_stock_data as _fetch_stock_data,
)
from rules import screen_stock


@st.cache_data(ttl=600, show_spinner=False)
def fetch_stock_data_cached(symbol: str):
    """Cache successful fetches only (exceptions are not cached)."""
    return _fetch_stock_data(symbol)


NOT_AVAILABLE = "Not available"
PROHIBITED_KEYWORDS = (
    "bank", "financ", "insurance", "gambling", "alcohol", "tobacco",
    "adult", "entertainment", "weapon", "defense", "cannabis",
    "marijuana", "pork", "riba",
)
NEWS_FLAG_KEYWORDS = (
    "interest", "alcohol", "gambling", "weapon", "defense", "tobacco",
    "cannabis", "pork", "riba", "lawsuit", "fraud", "corruption",
)
WEAPONS_KEYWORDS = ("defense", "aerospace", "weapon", "military", "arms")
ISRAEL_KEYWORDS = ("israel", "israeli", "tel aviv", "jerusalem", "idf", "gaza", "west bank")

# ── TEMPORARY: Force fresh fetch for fintech testing ──────────────
# ── Remove or set to [] once CRCL and SPCX are verified ───────────
FORCE_REFRESH_TICKERS = []


@st.cache_resource(show_spinner=False)
def get_connection_pool() -> psycopg2_pool.SimpleConnectionPool:
    dsn = os.environ.get("DATABASE_URL") or settings.database_url
    return psycopg2_pool.SimpleConnectionPool(
        minconn=1,
        maxconn=5,
        dsn=dsn,
    )


@st.cache_resource(show_spinner=False)
def ensure_search_index() -> None:
    """
    Creates indexes on stocks table for fast search.
    Runs once at startup, skipped if already exists.
    """
    try:
        db_pool = get_connection_pool()
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_stocks_ticker
                    ON stocks (ticker_symbol);

                    CREATE INDEX IF NOT EXISTS idx_stocks_name
                    ON stocks (company_name);
                    """
                )
            conn.commit()
        finally:
            db_pool.putconn(conn)
    except Exception as exc:
        print(f"Index creation skipped: {exc}")


def _search_stocks_rows(query: str, *, limit: int = 10) -> list[tuple[str, str]]:
    if not query or len(query.strip()) < 1:
        return []
    query = query.strip()
    db_pool: psycopg2_pool.SimpleConnectionPool | None = None
    conn = None
    try:
        db_pool = get_connection_pool()
        conn = db_pool.getconn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ticker_symbol,
                    company_name
                FROM stocks
                WHERE
                    ticker_symbol ILIKE %s
                    OR company_name ILIKE %s
                ORDER BY
                    CASE
                        WHEN ticker_symbol ILIKE %s
                        THEN 0 ELSE 1
                    END,
                    market_cap DESC NULLS LAST
                LIMIT %s
                """,
                (
                    f"{query}%",
                    f"%{query}%",
                    f"{query}%",
                    limit,
                ),
            )
            rows = cur.fetchall()
        return [
            (
                str(row[0]).upper().strip(),
                str(row[1]).strip() if row[1] else "",
            )
            for row in rows
            if row and row[0]
        ]
    except Exception as exc:
        print(f"Search error: {exc}")
        return []
    finally:
        if conn is not None and db_pool is not None:
            db_pool.putconn(conn)


def _extract_news_item(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}
    content = item.get("content") or {}
    title = item.get("title") or item.get("headline") or content.get("title") or content.get("headline")
    canonical_url = content.get("canonicalUrl") or {}
    click_url = content.get("clickThroughUrl") or {}
    url = (
        item.get("link")
        or item.get("url")
        or canonical_url.get("url")
        or click_url.get("url")
        or ""
    )
    publisher = item.get("publisher") or content.get("provider", {}).get("displayName") or ""
    published = item.get("providerPublishTime") or content.get("pubDate") or ""
    if not isinstance(title, str) or not title.strip():
        return {}
    return {
        "title": title.strip(),
        "url": str(url).strip(),
        "publisher": str(publisher).strip(),
        "published": str(published).strip(),
    }

@st.cache_data(ttl=600, show_spinner=False)
def fetch_ui_enrichment_cached(symbol: str) -> dict:
    """Fetch optional UI fields from local cached DB data only."""
    return _fetch_company_enrichment(symbol)


PWA_HEAD = """
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Halal Stocks">
<meta name="theme-color" content="#0D1B2A">
<link rel="apple-touch-icon" href="/static/icon.png">
<link rel="manifest" href="/static/manifest.json">

<!-- Primary Meta Tags -->
<meta name="title" content="Halal Stock Checker | iRizq">
<meta name="description" content="Check if a stock aligns with Islamic principles.">

<!-- Open Graph / WhatsApp / Facebook -->
<meta property="og:type" content="website">
<meta property="og:url" content="https://halal-stock-checker-irizq.streamlit.app/">
<meta property="og:title" content="Halal Stock Checker | iRizq">
<meta property="og:description" content="Check if a stock aligns with Islamic principles.">
<meta property="og:image" content="https://www.irizq.com/images/irizq_mobile.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:site_name" content="iRizq.com">

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Halal Stock Checker | iRizq">
<meta name="twitter:description" content="Check if a stock aligns with Islamic principles.">
<meta name="twitter:image" content="https://www.irizq.com/images/irizq_mobile.png">
"""

STATIC_INDEX_SOCIAL_HEAD = """
    <!-- Primary Meta Tags -->
    <meta name="title" content="Halal Stock Checker | iRizq">
    <meta name="description" content="Check if a stock aligns with Islamic principles.">

    <!-- Open Graph / WhatsApp / Facebook -->
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://halal-stock-checker-irizq.streamlit.app/">
    <meta property="og:title" content="Halal Stock Checker | iRizq">
    <meta property="og:description" content="Check if a stock aligns with Islamic principles.">
    <meta property="og:image" content="https://www.irizq.com/images/irizq_mobile.png">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">
    <meta property="og:site_name" content="iRizq.com">

    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="Halal Stock Checker | iRizq">
    <meta name="twitter:description" content="Check if a stock aligns with Islamic principles.">
    <meta name="twitter:image" content="https://www.irizq.com/images/irizq_mobile.png">
"""


def patch_streamlit_index_metadata() -> None:
    """Patch Streamlit's static index so crawlers see the app title/metadata."""
    try:
        import streamlit.file_util as streamlit_file_util
    except Exception:
        return

    try:
        index_path = os.path.join(streamlit_file_util.get_static_dir(), "index.html")
        if not os.path.exists(index_path):
            return

        with open(index_path, "r", encoding="utf-8") as streamlit_index:
            index_html = streamlit_index.read()
    except OSError:
        return

    updated_html = index_html.replace(
        "<title>Streamlit</title>",
        "<title>Halal Stock Checker | iRizq</title>",
        1,
    )
    has_social_meta = (
        'property="og:title" content="Halal Stock Checker | iRizq"' in updated_html
    )
    if not has_social_meta and "</head>" in updated_html:
        updated_html = updated_html.replace(
            "</head>",
            f"{STATIC_INDEX_SOCIAL_HEAD}\n  </head>",
            1,
        )

    if updated_html == index_html:
        return

    try:
        with open(index_path, "w", encoding="utf-8") as streamlit_index:
            streamlit_index.write(updated_html)
    except OSError:
        return


# Ensure social crawlers receive non-default Streamlit metadata from the root HTML.
patch_streamlit_index_metadata()

IRIZQ_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  html, body, [class*="css"] {
    font-family: 'Inter', 'Segoe UI', sans-serif;
    background-color: #0D1B2A;
    color: #F5F5F5;
  }
  .main .block-container {
    padding: 0 1rem 2rem 1rem;
    max-width: 720px;
    margin: 0 auto;
  }
  h1 {
    color: #C9A84C !important;
    font-weight: 700 !important;
    font-size: 1.8rem !important;
    margin-bottom: 0.2rem !important;
  }
  h3 {
    color: #8A9BB0 !important;
    font-weight: 400 !important;
    font-size: 0.95rem !important;
    margin-top: 0 !important;
  }

  .app-header {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 0;
    padding: 0 0 0.75rem 0;
    margin: 0;
  }
  .app-header-logo {
    width: 62px;
    height: 62px;
    border-radius: 16px;
    object-fit: contain;
    margin-bottom: 0.55rem;
  }
  .app-header-title {
    color: #C9A84C;
    font-size: 1.8rem;
    font-weight: 800;
    line-height: 1.1;
  }
  .app-header-subtitle {
    color: #8A9BB0;
    font-size: 0.95rem;
    font-weight: 500;
    line-height: 1.2;
    margin-top: 0.35rem;
    margin-bottom: 0.85rem;
  }
  .app-header-subtitle a {
    color: #C9A84C;
    text-decoration: none;
  }
  div[data-testid="stTextInput"] {
    margin-top: 0.75rem !important;
  }
  div[data-testid="stTextInput"] label {
    margin-bottom: 0.2rem !important;
  }
  div[data-testid="stButton"] {
    margin-top: 0.25rem !important;
  }
  div[data-testid="stExpander"] {
    margin-top: 0.45rem !important;
  }
  h2 {
    color: #C9A84C !important;
    font-size: 1.1rem !important;
    font-weight: 600 !important;
    border-bottom: 1px solid #2A3F55;
    padding-bottom: 0.4rem;
    margin-top: 1.5rem !important;
  }
  .stTextInput > div > div > input {
    background-color: #162032 !important;
    color: #F5F5F5 !important;
    border: 1px solid #2A3F55 !important;
    border-radius: 8px !important;
    font-size: 1rem !important;
    padding: 0.6rem 1rem !important;
  }
  .stTextInput > div > div > input:focus {
    border-color: #C9A84C !important;
    box-shadow: 0 0 0 2px rgba(201, 168, 76, 0.2) !important;
  }
  .stButton > button {
    background-color: #C9A84C !important;
    color: #0D1B2A !important;
    font-weight: 700 !important;
    font-size: 1rem !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 0.6rem 2rem !important;
    width: 100% !important;
    transition: background-color 0.2s ease !important;
  }
  .stButton > button:hover {
    background-color: #E8C96A !important;
  }
  .autocomplete-anchor {
    position: relative;
    width: 100%;
    height: 0;
    z-index: 40;
  }
  .autocomplete-dropdown {
    position: absolute;
    top: 0.18rem;
    left: 0;
    right: 0;
    background: rgba(22, 32, 50, 0.96);
    border: 1px solid #2A3F55;
    border-radius: 12px;
    box-shadow: 0 18px 34px rgba(0, 0, 0, 0.35);
    backdrop-filter: blur(8px);
    overflow: hidden;
    max-height: 280px;
    overflow-y: auto;
  }
  .autocomplete-item {
    display: block;
    padding: 0.72rem 0.9rem;
    text-decoration: none;
    border-bottom: 1px solid #24384d;
    transition: background-color 0.15s ease;
  }
  .autocomplete-item:last-child {
    border-bottom: none;
  }
  .autocomplete-item:hover {
    background-color: #203046;
  }
  .autocomplete-item-symbol {
    color: #F5F5F5;
    font-size: 0.93rem;
    font-weight: 700;
    line-height: 1.25;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  }
  .autocomplete-item-name {
    color: #8A9BB0;
    font-size: 0.8rem;
    margin-top: 0.1rem;
    line-height: 1.25;
  }
  .autocomplete-empty {
    color: #8A9BB0;
    font-size: 0.8rem;
    padding: 0.72rem 0.9rem;
  }
  [class*="st-key-autocomplete_select_"] button {
    background: transparent !important;
    border: none !important;
    border-radius: 0 !important;
    color: #F5F5F5 !important;
    text-align: left !important;
    width: 100% !important;
    padding: 0.72rem 0.9rem !important;
    min-height: 0 !important;
    box-shadow: none !important;
    border-bottom: 1px solid #24384d !important;
  }
  [class*="st-key-autocomplete_select_"] button:hover {
    background-color: #203046 !important;
  }
  [class*="st-key-autocomplete_select_"] button p {
    white-space: pre-line !important;
    line-height: 1.25 !important;
    color: #F5F5F5 !important;
    font-weight: 700 !important;
    font-size: 0.93rem !important;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace !important;
  }
  [class*="st-key-autocomplete_select_"] + div .autocomplete-item-name {
    margin-top: -0.38rem;
    margin-bottom: 0.38rem;
    padding: 0 0.9rem;
  }
  [class*="st-key-autocomplete_select_"]:last-of-type button {
    border-bottom: none !important;
  }
  .autocomplete-spacer {
    height: 16rem;
  }
  @media (max-width: 480px) {
    .autocomplete-dropdown {
      max-height: 14.5rem;
      left: -0.1rem;
      right: -0.1rem;
    }
    .autocomplete-item {
      padding: 0.7rem 0.82rem;
    }
    .autocomplete-item-symbol {
      font-size: 0.88rem;
    }
    .autocomplete-item-name {
      font-size: 0.76rem;
    }
  }
  .result-card {
    background-color: #1A2B3C;
    border-radius: 12px;
    padding: 1.2rem 1.5rem;
    margin: 1rem 0;
    border: 1px solid #2A3F55;
  }
  .badge-halal {
    background-color: #1B5E20;
    color: #A5D6A7;
    border: 1px solid #2E7D32;
    border-radius: 20px;
    padding: 0.4rem 1.2rem;
    font-weight: 700;
    font-size: 1.1rem;
    display: inline-block;
  }
  .badge-not-halal {
    background-color: #7F1515;
    color: #FFCDD2;
    border: 1px solid #C62828;
    border-radius: 20px;
    padding: 0.4rem 1.2rem;
    font-weight: 700;
    font-size: 1.1rem;
    display: inline-block;
  }
  .badge-questionable {
    background-color: #7B4F00;
    color: #FFE0B2;
    border: 1px solid #F59E0B;
    border-radius: 20px;
    padding: 0.4rem 1.2rem;
    font-weight: 700;
    font-size: 1.1rem;
    display: inline-block;
  }
  .stDataFrame, table {
    background-color: #162032 !important;
    border-radius: 8px !important;
    overflow: hidden !important;
    width: 100%;
    border-collapse: collapse;
  }
  thead tr th {
    background-color: #1A2B3C !important;
    color: #C9A84C !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
    padding: 0.75rem 1rem;
    text-align: left;
  }
  tbody tr td {
    color: #F5F5F5 !important;
    font-size: 0.9rem !important;
    border-bottom: 1px solid #2A3F55 !important;
    padding: 0.65rem 1rem;
  }
  tbody tr:hover td {
    background-color: #1A2B3C !important;
  }
  .stAlert {
    border-radius: 8px !important;
    border-left-width: 4px !important;
  }
  .disclaimer {
    background-color: #162032;
    border: 1px solid #2A3F55;
    border-left: 4px solid #C9A84C;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    color: #8A9BB0;
    font-size: 0.82rem;
    margin-top: 2rem;
  }
  .company-info {
    background-color: #1A2B3C;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    border: 1px solid #2A3F55;
    margin: 0.8rem 0;
  }
  .company-field {
    margin-bottom: 0.75rem;
  }
  .company-field:last-child {
    margin-bottom: 0;
  }
  .company-label {
    display: block;
    color: #8A9BB0;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.2rem;
  }
  .company-value {
    display: block;
    color: #F5F5F5;
    font-size: 1rem;
    line-height: 1.35;
  }
  .company-value.name {
    color: #C9A84C;
    font-weight: 700;
    font-size: 1.15rem;
  }
  .company-value.ticker {
    color: #E8C96A;
    font-family: monospace;
    font-weight: 600;
  }
  .company-value.muted {
    color: #8A9BB0;
    font-style: italic;
  }
  .explanation-card {
    background-color: #1A2B3C;
    border-left: 4px solid #C9A84C;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    color: #F5F5F5;
    margin: 1rem 0;
    border: 1px solid #2A3F55;
    border-left: 4px solid #C9A84C;
  }
  .error-card {
    background-color: #162032;
    border: 1px solid #C9A84C;
    border-left: 4px solid #C9A84C;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    color: #F5F5F5;
    margin: 1rem 0;
  }
  .result-pass { color: #4CAF50; font-weight: 600; }
  .result-fail { color: #EF5350; font-weight: 600; }
  .result-unknown { color: #F59E0B; font-weight: 600; }
  .info-msg {
    background-color: #162032;
    border: 1px solid #2A3F55;
    border-left: 4px solid #C9A84C;
    border-radius: 8px;
    padding: 0.9rem 1.1rem;
    color: #8A9BB0;
    margin: 0.8rem 0;
  }
  .aaoifi-info-box details {
    background-color: #162032;
    border: 1px solid #2A3F55;
    border-radius: 8px;
    padding: 0.6rem 0.8rem;
    margin-top: 0.45rem;
  }
  .aaoifi-info-box summary {
    color: #C9A84C;
    font-size: 0.84rem;
    font-weight: 600;
    cursor: pointer;
    list-style: none;
  }
  .aaoifi-info-box summary::-webkit-details-marker {
    display: none;
  }
  .aaoifi-info-box summary::before {
    content: ">";
    display: inline-block;
    margin-right: 0.4rem;
    transition: transform 0.15s ease;
  }
  .aaoifi-info-box details[open] summary::before {
    transform: rotate(90deg);
  }
  .aaoifi-info-copy {
    color: #8A9BB0;
    font-size: 0.8rem;
    line-height: 1.45;
    margin-top: 0.55rem;
  }

  div[data-testid="stPopover"] button {
    background-color: transparent !important;
    color: #C9A84C !important;
    border: 1px solid #2A3F55 !important;
    border-radius: 999px !important;
    padding: 0.25rem 0.65rem !important;
    min-height: 0 !important;
    width: auto !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    margin-top: -0.25rem !important;
  }
  div[data-testid="stPopover"] button p {
    font-size: 0.78rem !important;
  }
  footer { visibility: hidden; }
  #MainMenu { visibility: hidden; }
  header { visibility: hidden; }
  hr.irizq-divider {
    border: none;
    border-top: 1px solid #2A3F55;
    margin: 1.2rem 0;
  }

  /* Tab styling */
  .stTabs [data-baseweb="tab-list"] {
    background-color: #0D1B2A;
    border-bottom: none !important;
    gap: 10px;
    overflow-x: hidden !important;
    margin-bottom: 0 !important;
  }
  .stTabs [data-baseweb="tab-border"],
  .stTabs [data-baseweb="tab-highlight"] {
    display: none !important;
  }
  .stTabs [data-baseweb="tab-panel"] {
    padding-top: 0 !important;
  }
  .stTabs [data-baseweb="tab-panel"] .overview-card:first-child,
  .stTabs [data-baseweb="tab-panel"] .metric-card:first-child {
    margin-top: 0.8rem !important;
  }

  .stTabs [data-baseweb="tab"] {
    background-color: #0A111D !important;
    color: #F5F5F5 !important;
    border: 1px solid #2A3F55 !important;
    border-radius: 999px !important;
    font-weight: 700;
    font-size: 1.12rem;
    padding: 0.65rem 1.25rem !important;
    min-height: 44px;
    font-family: 'Inter', sans-serif;
    justify-content: center !important;
  }
  .stTabs [aria-selected="true"] {
    background-color: #C9A84C !important;
    color: #0D1B2A !important;
    border: 1px solid #C9A84C !important;
    box-shadow: 0 0 0 1px rgba(201, 168, 76, 0.28) !important;
  }
  .stTabs [data-baseweb="tab"] p {
    font-size: 1.12rem !important;
    font-weight: 700 !important;
    line-height: 1.2 !important;
    white-space: nowrap !important;
  }
  @media (max-width: 480px) {
    .stTabs [data-baseweb="tab-list"] {
      gap: 6px !important;
      justify-content: space-between !important;
    }
    .stTabs [data-baseweb="tab"] {
      flex: 1 1 0 !important;
      min-width: 0 !important;
      max-width: 25% !important;
      padding: 0.55rem 0.25rem !important;
      min-height: 40px !important;
    }
    .stTabs [data-baseweb="tab"] p {
      font-size: 0.92rem !important;
      line-height: 1.15 !important;
      white-space: nowrap !important;
    }
  }

  /* Metric cards */
  .metric-card {
    background-color: #1A2B3C;
    border-radius: 12px;
    padding: 1.2rem 1.4rem;
    margin: 0.8rem 0;
    border: 1px solid #2A3F55;
  }
  .metric-title {
    color: #F5F5F5;
    font-weight: 600;
    font-size: 1rem;
    margin-bottom: 0.3rem;
  }
  .metric-value {
    color: #F5F5F5;
    font-size: 2rem;
    font-weight: 700;
    line-height: 1;
  }
  .metric-threshold {
    color: #8A9BB0;
    font-size: 0.82rem;
    margin-left: 0.5rem;
  }
  .metric-label {
    color: #8A9BB0;
    font-size: 0.82rem;
    margin-top: 0.8rem;
    line-height: 1.5;
  }

  /* At a glance rows */
  .glance-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.7rem 0;
    border-bottom: 1px solid #2A3F55;
  }
  .glance-row:last-child {
    border-bottom: none;
  }
  .glance-label {
    color: #8A9BB0;
    font-size: 0.9rem;
  }

  /* Warning banner */
  .warning-banner {
    background-color: #3D2800;
    border: 1px solid #F59E0B;
    border-left: 4px solid #F59E0B;
    border-radius: 8px;
    padding: 0.8rem 1rem;
    color: #FFE0B2;
    font-size: 0.85rem;
    margin-bottom: 1rem;
  }

  /* Ethical concern cards */
  .ethical-card {
    background-color: #1A2B3C;
    border-radius: 12px;
    padding: 1.2rem 1.4rem;
    margin: 0.8rem 0;
    border: 1px solid #2A3F55;
  }
  .ethical-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
  }
  .ethical-title {
    color: #F5F5F5;
    font-weight: 600;
    font-size: 0.95rem;
  }

  /* Score stars */
  .star-rating {
    color: #C9A84C;
    font-size: 1.1rem;
    letter-spacing: 2px;
  }

  /* Summary bullets */
  .summary-bullet {
    display: flex;
    align-items: flex-start;
    gap: 0.6rem;
    padding: 0.5rem 0;
    color: #F5F5F5;
    font-size: 0.9rem;
    line-height: 1.5;
  }

  /* Plain English summary */
  .plain-english {
    background-color: #162032;
    border-left: 4px solid #C9A84C;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    color: #F5F5F5;
    font-size: 0.92rem;
    line-height: 1.6;
    margin-top: 1rem;
  }

  /* News item */
  .news-item {
    padding: 0.6rem 0;
    border-bottom: 1px solid #2A3F55;
    color: #F5F5F5;
    font-size: 0.88rem;
    line-height: 1.4;
  }
  .news-item:last-child {
    border-bottom: none;
  }
  .news-flag {
    color: #F59E0B;
    font-weight: 600;
    font-size: 0.8rem;
  }

  .overview-card {
    background-color: #1A2B3C;
    border-left: 4px solid #C9A84C;
    border-radius: 12px;
    padding: 1.2rem 1.4rem;
    margin: 0.8rem 0;
    border-top: 1px solid #2A3F55;
    border-right: 1px solid #2A3F55;
    border-bottom: 1px solid #2A3F55;
  }
  .muted-copy {
    color: #8A9BB0;
    font-size: 0.86rem;
    line-height: 1.5;
  }
  .card-title {
    color: #C9A84C;
    font-size: 1rem;
    font-weight: 700;
    margin-bottom: 0.7rem;
  }
  .mini-pill {
    border-radius: 999px;
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    padding: 0.28rem 0.65rem;
  }
  .missing-data {
    color: #8A9BB0;
    font-style: italic;
  }
  .calc-breakdown-box {
    background-color: #162032;
    border: 1px solid #2A3F55;
    border-radius: 10px;
    padding: 0.55rem 0.7rem;
    margin: 0.45rem 0 0.25rem 0;
  }
  .calc-breakdown-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.8rem;
    margin: 0.16rem 0;
  }
  .calc-breakdown-label {
    color: #F5F5F5;
    font-size: 0.8rem;
    min-width: 0;
    white-space: normal;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  }
  .calc-breakdown-value {
    color: #8A9BB0;
    font-size: 0.8rem;
    font-weight: 600;
    flex-shrink: 0;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  }
  .calc-breakdown-indent-1 {
    margin-left: 1rem;
  }
  .calc-result-line {
    color: #F5F5F5;
    font-size: 0.82rem;
    margin-top: 0.35rem;
    margin-bottom: 0.15rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  }
  .calc-footer-advisory {
    background-color: #1A2B3C;
    border-left: 4px solid #C9A84C;
    border-radius: 10px;
    padding: 0.75rem 0.9rem;
    margin-top: 0.8rem;
    color: #F5F5F5;
    font-size: 0.83rem;
    line-height: 1.45;
  }
  .calc-footer-note {
    background-color: #162032;
    border: 1px solid #2A3F55;
    border-radius: 10px;
    padding: 0.7rem 0.9rem;
    margin-top: 0.55rem;
    color: #8A9BB0;
    font-size: 0.79rem;
    line-height: 1.4;
  }
  @media (max-width: 480px) {
    .calc-breakdown-label,
    .calc-breakdown-value,
    .calc-result-line {
      font-size: 0.74rem;
    }
    .calc-footer-advisory,
    .calc-footer-note {
      font-size: 0.74rem;
    }
  }

</style>
"""

RESULT_ICONS = {
    "pass": "&#9989;",
    "fail": "&#10060;",
    "unknown": "&#9888;&#65039;",
}


def _logo_data_uri(logo_path: str) -> str:
    try:
        with open(logo_path, "rb") as logo_file:
            encoded_logo = base64.b64encode(logo_file.read()).decode("ascii")
    except OSError:
        return ""
    return f"data:image/png;base64,{encoded_logo}"


def _app_header_html(logo_path: str) -> str:
    logo_src = _logo_data_uri(logo_path)
    logo_html = (
        f'<img src="{logo_src}" alt="iRizq" class="app-header-logo">'
        if logo_src
        else ""
    )
    return f'''
    <div class="app-header">
      <a href="https://www.irizq.com" target="_blank" style="text-decoration:none;">{logo_html}</a>
      <div class="app-header-title">Halal Stock Checker</div>
      <div class="app-header-subtitle">AAOIFI-Based Screening Powered by <a href="https://www.iRizq.com" target="_blank">iRizq.com</a></div>
    </div>
    '''


def inject_head_and_styles() -> None:
    st.markdown(PWA_HEAD + IRIZQ_CSS, unsafe_allow_html=True)


def render_disclaimer() -> None:
    st.markdown(
        """
        <div class="disclaimer">
        &#9888;&#65039; This tool is for educational purposes only and does not constitute
        a fatwa or financial advice. Always consult a qualified Islamic finance scholar
        for personal guidance. | iRizq.com
        </div>
        """,
        unsafe_allow_html=True,
    )


def badge_html(result: str) -> str:
    if result == "Halal":
        return '<span class="badge-halal">&#9989; HALAL</span>'
    if result == "Not Halal":
        return '<span class="badge-not-halal">&#10060; NOT HALAL</span>'
    return '<span class="badge-questionable">&#9888;&#65039; QUESTIONABLE</span>'


def result_cell(row: dict) -> str:
    cls = row.get("result_class", "unknown")
    icon = RESULT_ICONS.get(cls, RESULT_ICONS["unknown"])
    label = row.get("result", "Unknown")
    css = {"pass": "result-pass", "fail": "result-fail"}.get(cls, "result-unknown")
    return f'<span class="{css}">{icon} {label}</span>'


def breakdown_table_html(rows: list[dict]) -> str:
    body = ""
    for row in rows:
        body += (
            f"<tr>"
            f"<td>{row['check']}</td>"
            f"<td>{row['value']}</td>"
            f"<td>{row['threshold']}</td>"
            f"<td>{result_cell(row)}</td>"
            f"</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Check</th><th>Value</th><th>Threshold</th><th>Result</th>"
        "</tr></thead><tbody>"
        + body
        + "</tbody></table>"
    )


def _display_profile_field(label: str, value: str, value_class: str = "") -> str:
    safe_label = html.escape(label)
    safe_value = html.escape(value)
    cls = f"company-value {value_class}".strip()
    return (
        f'<div class="company-field">'
        f'<span class="company-label">{safe_label}</span>'
        f'<span class="{cls}">{safe_value}</span>'
        f"</div>"
    )


def _format_sector_industry(sector: str, industry: str) -> tuple[str, str]:
    sector = (sector or "").strip()
    industry = (industry or "").strip()
    unknown = {"", "unknown", "n/a", "na", "none"}
    sector_ok = sector and sector.lower() not in unknown
    industry_ok = industry and industry.lower() not in unknown
    sector_display = sector if sector_ok else "Not available"
    industry_display = industry if industry_ok else "Not available"
    if not sector_ok:
        sector_display = "Not available"
    if not industry_ok:
        industry_display = "Not available"
    return sector_display, industry_display



def _is_available_text(value: str) -> bool:
    return bool(value and value not in {"Not available", NOT_AVAILABLE})


def _safe_text(value: object, fallback: str = NOT_AVAILABLE) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"unknown", "n/a", "na", "none", "null"}:
        return fallback
    return text


def _format_money(value: float | int | None) -> str:
    if value is None:
        return NOT_AVAILABLE
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return NOT_AVAILABLE
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1_000_000_000_000:
        return f"{sign}${amount / 1_000_000_000_000:.2f}T"
    if amount >= 1_000_000_000:
        return f"{sign}${amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"{sign}${amount / 1_000_000:.2f}M"
    return f"{sign}${amount:,.0f}"


def _format_ratio(value: float | None) -> str:
    if value is None:
        return NOT_AVAILABLE
    return f"{value * 100:.1f}%"


def _result_kind(result: str) -> str:
    if result == "Halal":
        return "pass"
    if result == "Not Halal":
        return "fail"
    return "questionable"


def _pill(label: str, kind: str) -> str:
    styles = {
        "pass": ("#1B5E20", "#A5D6A7", "#2E7D32"),
        "fail": ("#7F1515", "#FFCDD2", "#C62828"),
        "questionable": ("#7B4F00", "#FFE0B2", "#F59E0B"),
        "limited": ("#162032", "#C9A84C", "#2A3F55"),
        "neutral": ("#162032", "#8A9BB0", "#2A3F55"),
    }
    bg, fg, border = styles.get(kind, styles["neutral"])
    return f'<span class="mini-pill" style="background-color:{bg};color:{fg};border:1px solid {border};">{html.escape(label)}</span>'


def _status_badge(result: str, *, large: bool = False) -> str:
    kind = _result_kind(result)
    if kind == "pass":
        label = "🟢 HALAL"
    elif kind == "fail":
        label = "🔴 NOT HALAL"
    else:
        label = "🟡 QUESTIONABLE"

    if not large:
        return _pill(label, kind)

    colors = {
        "pass": ("#1B5E20", "#A5D6A7", "#2E7D32"),
        "fail": ("#7F1515", "#FFCDD2", "#C62828"),
        "questionable": ("#7B4F00", "#FFE0B2", "#F59E0B"),
    }
    bg, fg, border = colors[kind]
    return (
        f'<span style="background-color:{bg};color:{fg};border:1px solid {border};'
        'border-radius:999px;display:inline-block;font-size:1rem;font-weight:800;'
        'letter-spacing:0.03em;padding:0.5rem 1rem;">'
        f'{html.escape(label)}</span>'
    )


def _breakdown_row(screening: dict, check_name: str) -> dict:
    for row in screening.get("breakdown", []):
        if check_name.lower() in str(row.get("check", "")).lower():
            return row
    return {}


def _ratio_status(value: float | None, threshold: float, questionable_floor: float | None = None) -> str:
    if value is None:
        return "unavailable"
    if value > threshold:
        return "fail"
    if value + 1e-12 >= threshold * 0.9:
        return "questionable"
    return "pass"

def _ratio_color(status: str) -> str:
    return {"pass": "#4CAF50", "questionable": "#F59E0B", "fail": "#EF5350"}.get(status, "#8A9BB0")


def _calculate_score(screening: dict) -> int:
    score = 100
    business_row = _breakdown_row(screening, "Business")
    if business_row.get("result_class") == "fail":
        score -= 40
    has_questionable = False
    for key, threshold, floor in (("debt_ratio", 0.33, 0.28), ("cash_ratio", 0.33, 0.28), ("income_ratio", 0.05, 0.04)):
        status = _ratio_status(screening.get(key), threshold, floor)
        if status == "fail":
            score -= 20
        elif status == "questionable":
            has_questionable = True
    if has_questionable:
        score -= 10
    return max(score, 0)


def _score_label(score: int) -> tuple[str, str, str]:
    if score >= 80:
        return "Excellent", "#4CAF50", "⭐⭐⭐⭐⭐"
    if score >= 65:
        return "Good", "#8BC34A", "⭐⭐⭐⭐"
    if score >= 50:
        return "Borderline", "#F59E0B", "⭐⭐⭐"
    return "Poor", "#EF5350", "⭐⭐"


def _confidence_level(data: dict, screening: dict) -> int:
    score = 100
    sector, industry = _format_sector_industry(data.get("sector", ""), data.get("industry", ""))
    if not _is_available_text(sector):
        score -= 20
    if not _is_available_text(industry):
        score -= 15
    if data.get("market_cap") in (None, 0):
        score -= 25
    if data.get("total_revenue") in (None, 0):
        score -= 20
    if any(screening.get(key) is None for key in ("debt_ratio", "cash_ratio", "income_ratio")):
        score -= 10
    return max(0, min(100, score))


def _progress_bar_html(value: float, threshold_pct: float | None, color: str) -> str:
    pct = max(0, min(float(value), 100))
    marker = ""
    if threshold_pct is not None:
        threshold = max(0, min(float(threshold_pct), 100))
        marker = f'<div style="position:absolute;left:{threshold}%;top:-4px;width:2px;height:20px;background-color:#C9A84C;"></div><div style="position:absolute;left:{threshold}%;top:20px;font-size:0.7rem;color:#C9A84C;transform:translateX(-50%);">Limit</div>'
    return f'<div style="position:relative;margin:1rem 0 1.4rem 0;"><div style="background-color:#162032;border-radius:6px;height:12px;overflow:visible;position:relative;"><div style="width:{pct}%;background-color:{color};height:12px;border-radius:6px;transition:width 0.5s ease;"></div>{marker}</div></div>'


def _company_logo_html(info: dict, company: str) -> str:
    first_letter = html.escape((company.strip()[:1] or "?").upper())
    fallback = f'<div style="width:56px;height:56px;background-color:#1A2B3C;border:2px solid #C9A84C;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:1.5rem;font-weight:700;color:#C9A84C;position:absolute;inset:0;">{first_letter}</div>'
    website = _safe_text(info.get("website"), "")
    domain = ""
    if website:
        parsed = urlparse(website if "://" in website else f"https://{website}")
        domain = (parsed.netloc or parsed.path).split("/")[0]
    if not domain:
        return f'<div style="position:relative;width:56px;height:56px;">{fallback}</div>'
    logo_url = f"https://logo.clearbit.com/{html.escape(domain)}"
    return f'<div style="position:relative;width:56px;height:56px;flex:0 0 56px;">{fallback}<img src="{logo_url}" alt="" onerror="this.style.display=\'none\';" style="position:absolute;inset:0;width:56px;height:56px;border-radius:50%;object-fit:cover;border:2px solid #C9A84C;background-color:#1A2B3C;"></div>'


def _build_enriched_stock_data(stock_data: dict, enrichment: dict) -> dict:
    enriched = dict(stock_data)
    enriched["_ui_info"] = enrichment.get("info", {})
    enriched["_ui_news"] = enrichment.get("news", [])
    enriched["_ui_cashflow_available"] = enrichment.get("cashflow_available", False)
    enriched["_ui_news_available"] = enrichment.get("news_available", False)
    return enriched


def _company_name(data: dict) -> str:
    symbol = data.get("symbol", "N/A")
    company = (data.get("company_name") or data.get("_ui_info", {}).get("longName") or "").strip()
    if not company or company.upper() == str(symbol).upper():
        return "Name unavailable - verify ticker"
    return company


def _financial_statuses(screening: dict) -> dict[str, str]:
    return {
        "debt": _ratio_status(screening.get("debt_ratio"), 0.33, 0.28),
        "cash": _ratio_status(screening.get("cash_ratio"), 0.33, 0.28),
        "income": _ratio_status(screening.get("income_ratio"), 0.05, 0.04),
    }


def _is_core_interest_business(data: dict) -> bool:
    info = data.get("_ui_info", {}) if isinstance(data.get("_ui_info", {}), dict) else {}
    profile_parts = [
        data.get("symbol", ""),
        data.get("sector", ""),
        data.get("industry", ""),
        data.get("company_name", ""),
        info.get("sector", ""),
        info.get("industry", ""),
        info.get("longName", ""),
    ]
    profile = " ".join(str(part) for part in profile_parts).lower()
    core_tickers = {
        "JPM", "C", "BAC", "WFC", "USB", "PNC", "TFC",
        "AIG", "MET", "PRU", "ALL", "TRV",
    }
    symbol = str(data.get("symbol", "")).upper()
    if symbol in core_tickers:
        return True

    keywords = (
        "bank",
        "banks",
        "banking",
        "insurance",
        "insurer",
        "reinsurance",
    )
    return any(keyword in profile for keyword in keywords)


def _display_result(data: dict, screening: dict) -> str:
    business_row = _breakdown_row(screening, "Business")
    business_class = business_row.get("result_class", "unknown")
    statuses = _financial_statuses(screening)
    if business_class == "fail" or "fail" in statuses.values():
        return "Not Halal"
    if business_class == "unknown" or any(status in {"questionable", "unavailable"} for status in statuses.values()):
        return "Questionable / Needs Scholar Review"
    return "Halal"


def _criteria_summary(data: dict, screening: dict) -> tuple[int, int, list[str]]:
    statuses = _financial_statuses(screening)
    business_row = _breakdown_row(screening, "Business")
    profile_text = " ".join(str(data.get(key, "")) for key in ("sector", "industry"))
    news_text = " ".join(item.get("title", "") for item in data.get("_ui_news", []) if isinstance(item, dict))
    ethical_clear = not _contains_keyword(f"{profile_text} {news_text}", NEWS_FLAG_KEYWORDS + WEAPONS_KEYWORDS)
    checks = [
        ("Business", business_row.get("result_class") == "pass"),
        ("Debt", statuses["debt"] == "pass"),
        ("Cash", statuses["cash"] == "pass"),
        ("Income", statuses["income"] == "pass"),
        ("Ethical", ethical_clear),
    ]
    return sum(1 for _, passed in checks if passed), len(checks), [label for label, passed in checks if passed]

def _main_issue(screening: dict) -> str:
    business_row = _breakdown_row(screening, "Business")
    if business_row.get("result_class") == "unknown":
        return "Business activity could not be fully verified from available sector data."
    ratios = [("Debt Ratio", screening.get("debt_ratio"), 0.33), ("Cash Ratio", screening.get("cash_ratio"), 0.33), ("Income Ratio", screening.get("income_ratio"), 0.05)]
    available = [(name, value, threshold) for name, value, threshold in ratios if value is not None]
    if not available:
        return "Financial statement data is incomplete."
    name, value, threshold = min(available, key=lambda item: abs(item[2] - item[1]))
    return f"{name} is closest to its {threshold * 100:.0f}% threshold at {value * 100:.1f}%."

def _render_overview_tab(data: dict, screening: dict) -> None:
    symbol = html.escape(str(data.get("symbol", "N/A")))
    company = _company_name(data)
    sector, industry = _format_sector_industry(data.get("sector", ""), data.get("industry", ""))
    info = data.get("_ui_info", {})
    exchange = _safe_text(info.get("exchange"))
    result = _display_result(data, screening)
    passed, total, passed_labels = _criteria_summary(data, screening)
    passed_copy = ", ".join(passed_labels) if passed_labels else "No criteria fully passed yet"
    # ── DATA FRESHNESS DATES — update these manually ──────────────────
    # stock_last_updated:      update every Sunday after price download
    # financial_last_updated:  update each quarter after SEC data download
    # financial_quarter_label: e.g. "Q1 2025", "Q2 2025" etc.
    # ──────────────────────────────────────────────────────────────────
    stock_last_updated = datetime.date(2025, 6, 1)
    financial_last_updated = datetime.date(2025, 3, 31)
    financial_quarter_label = "Q1 2025"
    data_last_updated_html = """
    <div style="font-size: 13px; color: #888; line-height: 1.8;">
        <strong style="color: #888;">Data Last Updated</strong><br>
        Stock Price &amp; Market Cap: &nbsp;<span style="color: #888;">
            {stock_date}
        </span><br>
        Financial Data (SEC): &nbsp;<span style="color: #888;">
            {financial_date}
        </span>
    </div>
    """.format(
        stock_date=stock_last_updated.strftime("%B %d, %Y"),
        financial_date=financial_last_updated.strftime("%B %d, %Y") + f" ({financial_quarter_label})",
    )
    st.markdown(f'''
        <div class="overview-card">
          <div style="display:flex;gap:0.9rem;align-items:center;">
            {_company_logo_html(info, company)}
            <div><div style="color:#C9A84C;font-size:1.12rem;font-weight:800;line-height:1.25;">{html.escape(company)}</div><div style="color:#E8C96A;font-family:monospace;font-size:0.9rem;margin-top:0.15rem;">{symbol}</div></div>
          </div>
          <div class="muted-copy" style="margin-top:0.9rem;">{html.escape(industry)} • {html.escape(exchange)}</div>
          <div style="margin-top:0.85rem;">{_status_badge(result, large=True)}</div>
          <div style="margin-top:1rem;background-color:#162032;border-radius:10px;padding:0.9rem 1rem;border:1px solid #2A3F55;">
            <div style="color:#C9A84C;font-weight:800;font-size:1.25rem;">{passed}/{total}</div>
            <div class="muted-copy">Screening criteria passed</div>
            <div class="muted-copy" style="margin-top:0.35rem;">Passed: {html.escape(passed_copy)}</div>
          </div>
          <div class="muted-copy" style="margin-top:0.8rem;">{data_last_updated_html}</div>
        </div>
        ''', unsafe_allow_html=True)
    _render_at_a_glance(data, screening)
    _render_quick_summary(data, screening)
    _render_purification_estimator_card(data, screening)

def _render_quick_summary(data: dict, screening: dict) -> None:
    result = _display_result(data, screening)
    business_row = _breakdown_row(screening, "Business")
    business_class = business_row.get("result_class", "unknown")
    financial_statuses = _financial_statuses(screening)
    if business_class == "pass":
        business_icon, business_text = "✅", "Business activity appears permissible from sector and industry data."
        prohibited_icon, prohibited_text = "✅", "Prohibited activity: none detected in available profile data."
    elif business_class == "fail":
        business_icon, business_text = "❌", "Business activity appears prohibited based on sector or industry."
        prohibited_icon, prohibited_text = "❌", "Prohibited activity: detected in available profile data."
    else:
        business_icon, business_text = "⚠️", "Business activity is unclear from available data."
        prohibited_icon, prohibited_text = "⚠️", "Prohibited activity: possible concern due to limited profile data."
    if "fail" in financial_statuses.values():
        financial_icon, financial_text = "❌", "Financial ratios are exceeding one or more AAOIFI limits."
    elif "questionable" in financial_statuses.values() or "unavailable" in financial_statuses.values():
        financial_icon, financial_text = "⚠️", "Financial ratios are near a threshold or missing from available data."
    else:
        financial_icon, financial_text = "✅", "Financial ratios are within AAOIFI screening limits."
    issue_html = f"<div style='margin-top:0.7rem;color:#F59E0B;font-weight:700;'>Main issue: {html.escape(_main_issue(screening))}</div>" if _result_kind(result) == "questionable" else ""
    st.markdown(f'''
        <div class="overview-card"><div class="card-title">Quick Summary</div>
          <div class="summary-bullet"><span>{business_icon}</span><span>{business_text}</span></div>
          <div class="summary-bullet"><span>{financial_icon}</span><span>{financial_text}</span></div>
          <div class="summary-bullet"><span>{prohibited_icon}</span><span>{prohibited_text}</span></div>{issue_html}
        </div>''', unsafe_allow_html=True)


def _render_at_a_glance(data: dict, screening: dict) -> None:
    business_row = _breakdown_row(screening, "Business")
    business_kind = {"pass": "pass", "fail": "fail", "unknown": "questionable"}.get(business_row.get("result_class", "unknown"), "questionable")
    statuses = _financial_statuses(screening)
    if "fail" in statuses.values():
        financial_kind, financial_label = "fail", "NOT HALAL"
    elif "questionable" in statuses.values() or "unavailable" in statuses.values():
        financial_kind, financial_label = "questionable", "QUESTIONABLE"
    else:
        financial_kind, financial_label = "pass", "HALAL"
    ethical_flags = _ethical_flag_count(data)
    ethical_badge = _pill(f"{ethical_flags} Flags", "questionable") if ethical_flags > 0 else _pill("Clear", "pass")
    rows = [
        ("Business Activity", _pill("HALAL" if business_kind == "pass" else "NOT HALAL" if business_kind == "fail" else "QUESTIONABLE", business_kind)),
        ("Financial Screening", _pill(financial_label, financial_kind)),
        ("Ethical Insights", ethical_badge),
        ("Overall", _status_badge(_display_result(data, screening))),
    ]
    body = "".join(f'<div class="glance-row"><span class="glance-label">{html.escape(label)}</span>{badge}</div>' for label, badge in rows)
    st.markdown(f'<div class="overview-card"><div class="card-title">At a Glance</div>{body}</div>', unsafe_allow_html=True)

def _metric_data(data: dict, metric: str) -> tuple[float | None, float | None, float | None]:
    if _is_core_interest_business(data):
        if metric == "debt":
            return data.get("total_debt"), data.get("market_cap"), None
        if metric == "cash":
            return _resolve_liquid_component_totals(data)["total_interest_earning_pools"], data.get("market_cap"), None
        return data.get("interest_income"), data.get("total_revenue"), None

    if metric == "debt":
        numerator, denominator = data.get("total_debt"), data.get("market_cap")
    elif metric == "cash":
        numerator, denominator = _resolve_liquid_component_totals(data)["total_interest_earning_pools"], data.get("market_cap")
    else:
        numerator, denominator = data.get("interest_income"), data.get("total_revenue")
    if numerator is None or denominator in (None, 0):
        return numerator, denominator, None
    try:
        return float(numerator), float(denominator), float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError):
        return numerator, denominator, None


def _income_ratio_disclaimer(data: dict) -> str | None:
    data_source = data.get("_data_source")
    if not isinstance(data_source, dict):
        return None
    mapped_tags = data_source.get("mapped_tags")
    if not isinstance(mapped_tags, dict):
        return None
    interest_meta = mapped_tags.get("interest_income")
    if not isinstance(interest_meta, dict):
        return None
    disclaimer = interest_meta.get("fallback_disclaimer")
    if not disclaimer:
        return None
    return str(disclaimer)


def _calc_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def _format_money_calc(value: object) -> str:
    amount = _calc_float(value)
    if amount is None:
        return NOT_AVAILABLE
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount == 0:
        return "$0.00"
    if amount >= 1_000_000_000_000:
        return f"{sign}${amount / 1_000_000_000_000:.2f}T"
    if amount >= 1_000_000_000:
        return f"{sign}${amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"{sign}${amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"{sign}${amount:,.2f}"
    return f"{sign}${amount:.2f}"


def _format_units_count(value: object) -> str:
    amount = _calc_float(value)
    if amount is None:
        return NOT_AVAILABLE
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount == 0:
        return "0"
    if amount >= 1_000_000_000_000:
        return f"{sign}{amount / 1_000_000_000_000:.2f}T"
    if amount >= 1_000_000_000:
        return f"{sign}{amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"{sign}{amount / 1_000_000:.2f}M"
    if amount >= 1_000:
        return f"{sign}{amount:,.0f}"
    return f"{sign}{amount:.0f}"


def _nested_component_map(data: dict) -> dict[str, dict]:
    mapped_tags = ((data.get("_data_source") or {}).get("mapped_tags") or {})
    components = (mapped_tags.get("components") if isinstance(mapped_tags, dict) else None) or {}
    valuation_fallback = ((data.get("_data_source") or {}).get("market_cap_fallback") or {})

    valuation = dict(components.get("valuation") or {})
    valuation.setdefault("baseline_label", "Market Cap Baseline")
    if valuation.get("shares_outstanding") is None:
        valuation["shares_outstanding"] = valuation_fallback.get("shares_outstanding")
    if valuation.get("latest_closing_price") is None:
        valuation["latest_closing_price"] = valuation_fallback.get("close_price")

    debt = dict(components.get("debt") or {})
    debt.setdefault("total_borrowed_capital", data.get("total_debt"))

    liquid = dict(components.get("liquid_assets") or {})
    liquid.setdefault("total_interest_earning_pools", data.get("cash"))

    purging = dict(components.get("purging") or {})
    interest_meta = mapped_tags.get("interest_income") if isinstance(mapped_tags, dict) else None
    if isinstance(interest_meta, dict) and not purging.get("calculation_details"):
        calc_details = interest_meta.get("calculationDetails")
        if isinstance(calc_details, list):
            purging["calculation_details"] = calc_details
    interest_income = _calc_float(data.get("interest_income"))
    total_prohibited = _calc_float(purging.get("total_annual_prohibited_revenue"))
    # Backward-compatible guard for previously stored rows where purging total
    # remained 0/None while resolved interest_income was populated by fallback.
    if (
        interest_income is not None
        and (total_prohibited is None or (total_prohibited == 0.0 and interest_income != 0.0))
    ):
        purging["total_annual_prohibited_revenue"] = interest_income
    else:
        purging.setdefault("total_annual_prohibited_revenue", data.get("interest_income"))

    passive_yield = _calc_float(purging.get("passive_financial_yield"))
    if passive_yield is None:
        inferred_passive = _sum_present(
            [
                _calc_float(purging.get("non_operating_cash_interest")),
                _calc_float(purging.get("equity_investment_dividends")),
            ]
        )
        if inferred_passive is not None:
            purging["passive_financial_yield"] = inferred_passive
            passive_yield = inferred_passive
    if passive_yield in (None, 0.0) and interest_income not in (None, 0.0):
        fallback_step = (
            str(interest_meta.get("fallback_step") or "").strip().lower()
            if isinstance(interest_meta, dict)
            else ""
        )
        if fallback_step in {"step2", "step3"}:
            purging["passive_financial_yield"] = interest_income

    purging.setdefault("total_revenue_baseline", data.get("total_revenue"))
    if purging.get("core_prohibited_operations") is None:
        purging["core_prohibited_operations"] = 0.0

    return {
        "valuation": valuation,
        "debt": debt,
        "liquid_assets": liquid,
        "purging": purging,
    }


def _sum_present(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)


def _resolve_liquid_component_totals(data: dict) -> dict[str, float | None]:
    liquid = _nested_component_map(data)["liquid_assets"]

    bank_cash = _calc_float(liquid.get("bank_cash"))
    restricted_cash = _calc_float(liquid.get("restricted_cash_reserves"))
    short_term_securities = _calc_float(liquid.get("short_term_securities"))
    long_term_bonds = _calc_float(liquid.get("long_term_bonds_paper"))

    cash_and_equivalents = _calc_float(liquid.get("cash_and_cash_equivalents"))
    if cash_and_equivalents is None:
        cash_and_equivalents = _sum_present([bank_cash, restricted_cash])

    # Always prefer a strict recompute from short-term + long-term securities.
    marketable_debt_securities = _sum_present([short_term_securities, long_term_bonds])
    if marketable_debt_securities is None:
        marketable_debt_securities = _calc_float(liquid.get("marketable_debt_securities"))

    # Ratio 2 numerator should include both parent buckets.
    total_interest_earning_pools = _sum_present([cash_and_equivalents, marketable_debt_securities])
    if total_interest_earning_pools is None:
        total_interest_earning_pools = _calc_float(liquid.get("total_interest_earning_pools"))
    if total_interest_earning_pools is None:
        total_interest_earning_pools = _calc_float(data.get("cash"))

    return {
        "cash_and_equivalents": cash_and_equivalents,
        "marketable_debt_securities": marketable_debt_securities,
        "total_interest_earning_pools": total_interest_earning_pools,
        "bank_cash": bank_cash,
        "restricted_cash_reserves": restricted_cash,
        "short_term_securities": short_term_securities,
        "long_term_bonds_paper": long_term_bonds,
    }


def _calc_row_html(label: str, value: object, *, depth: int = 0, units: bool = False) -> str:
    value_label = _format_units_count(value) if units else _format_money_calc(value)
    indent_cls = " calc-breakdown-indent-1" if depth > 0 else ""
    return (
        f'<div class="calc-breakdown-row{indent_cls}">'
        f'<span class="calc-breakdown-label">{html.escape(label)}</span>'
        f'<span class="calc-breakdown-value">{html.escape(value_label)}</span>'
        "</div>"
    )


def _render_calc_rows(rows: list[dict[str, object]]) -> None:
    body = "".join(
        _calc_row_html(
            str(row.get("label") or ""),
            row.get("value"),
            depth=int(row.get("depth") or 0),
            units=bool(row.get("units")),
        )
        for row in rows
    )
    st.markdown(f'<div class="calc-breakdown-box">{body}</div>', unsafe_allow_html=True)


def _calculation_details_for_metric(
    data: dict,
    metric: str,
    numerator: float | None,
    denominator: float | None,
    numerator_label: str,
    denominator_label: str,
) -> tuple[str, list[dict[str, object]], str, list[dict[str, object]]]:
    components = _nested_component_map(data)
    valuation = components["valuation"]
    debt = components["debt"]
    liquid = components["liquid_assets"]
    purging = components["purging"]

    short_term_borrowings = _calc_float(debt.get("short_term_borrowings"))
    if short_term_borrowings is None:
        short_term_borrowings = (
            (_calc_float(debt.get("commercial_paper")) or 0.0)
            + (_calc_float(debt.get("short_term_notes_pay")) or 0.0)
        )
    long_term_borrowings = _calc_float(debt.get("long_term_borrowings"))
    if long_term_borrowings is None:
        long_term_borrowings = (
            (_calc_float(debt.get("current_long_term_debt")) or 0.0)
            + (_calc_float(debt.get("noncurrent_debt_obligations")) or 0.0)
        )

    liquid_totals = _resolve_liquid_component_totals(data)
    cash_and_equivalents = liquid_totals["cash_and_equivalents"]
    marketable_pools = liquid_totals["marketable_debt_securities"]

    passive_yield = _calc_float(purging.get("passive_financial_yield"))
    if passive_yield is None:
        passive_yield = (
            (_calc_float(purging.get("non_operating_cash_interest")) or 0.0)
            + (_calc_float(purging.get("equity_investment_dividends")) or 0.0)
        )

    numerator_rows: list[dict[str, object]]
    denominator_rows: list[dict[str, object]]
    numerator_title = numerator_label
    denominator_title = denominator_label

    if metric == "debt":
        numerator_title = "Total Debt"
        denominator_title = "Market Cap"
        numerator_rows = [
            {"label": "Total Borrowed Capital", "value": debt.get("total_borrowed_capital", numerator)},
            {"label": "Short-Term Borrowings", "value": short_term_borrowings},
            {"label": "Commercial Paper", "value": debt.get("commercial_paper"), "depth": 1},
            {"label": "Short-Term Notes Pay", "value": debt.get("short_term_notes_pay"), "depth": 1},
            {"label": "Long-Term Borrowings", "value": long_term_borrowings},
            {"label": "Current Long-Term Debt", "value": debt.get("current_long_term_debt"), "depth": 1},
            {"label": "Noncurrent Debt Obligations", "value": debt.get("noncurrent_debt_obligations"), "depth": 1},
        ]
    elif metric == "cash":
        numerator_title = "Total Cash"
        denominator_title = "Market Cap"
        numerator_rows = [
            {"label": "Total Interest-Earning Pools", "value": liquid_totals["total_interest_earning_pools"]},
            {"label": "Cash & Cash Equivalents", "value": cash_and_equivalents},
            {"label": "Bank Accounts / Cash", "value": liquid_totals["bank_cash"], "depth": 1},
            {"label": "Restricted Cash Reserves", "value": liquid_totals["restricted_cash_reserves"], "depth": 1},
            {"label": "Marketable Debt Securities", "value": marketable_pools},
            {"label": "Short-Term Securities", "value": liquid_totals["short_term_securities"], "depth": 1},
            {"label": "Long-Term Bonds & Paper", "value": liquid_totals["long_term_bonds_paper"], "depth": 1},
        ]
    else:
        numerator_title = "Total Annual Prohibited Revenue"
        denominator_title = "Total Revenue"
        numerator_rows = [
            {"label": "Total Annual Prohibited Revenue", "value": purging.get("total_annual_prohibited_revenue", numerator)},
            {"label": "Core Prohibited Operations", "value": purging.get("core_prohibited_operations")},
            {"label": "Passive Financial Yield", "value": passive_yield},
            {"label": "Non-Operating Cash Interest", "value": purging.get("non_operating_cash_interest"), "depth": 1},
            {"label": "Equity Investment Dividends", "value": purging.get("equity_investment_dividends"), "depth": 1},
        ]
        additional_details = purging.get("calculation_details")
        if isinstance(additional_details, list):
            for detail in additional_details:
                if not isinstance(detail, dict):
                    continue
                amount = detail.get("amount")
                if amount is None:
                    continue
                line_name = str(detail.get("lineName") or "Additional Impermissible Income")
                source_section = str(detail.get("sourceSection") or "").strip()
                label = line_name if not source_section else f"{line_name} ({source_section})"
                numerator_rows.append({"label": label, "value": amount, "depth": 1})

    baseline_label = valuation.get("baseline_label") or "Market Cap Baseline"
    denominator_rows = [
        {"label": baseline_label, "value": denominator if denominator is not None else data.get("market_cap")},
        {"label": "Shares Outstanding", "value": valuation.get("shares_outstanding"), "depth": 1, "units": True},
        {"label": "Latest Closing Price", "value": valuation.get("latest_closing_price"), "depth": 1},
    ]
    if metric == "income":
        denominator_rows = [
            {"label": "Total Revenue Baseline", "value": purging.get("total_revenue_baseline", denominator)},
        ]

    return numerator_title, numerator_rows, denominator_title, denominator_rows


def _result_line(numerator: float | None, denominator: float | None, ratio: float | None) -> str:
    if ratio is None:
        return f"Result: {NOT_AVAILABLE} = {_format_money_calc(numerator)} / {_format_money_calc(denominator)}"
    return (
        f"Result: {ratio * 100:.2f}% = {_format_money_calc(numerator)} / {_format_money_calc(denominator)}"
    )


def _render_metric_calculation(
    data: dict,
    metric: str,
    numerator: float | None,
    denominator: float | None,
    ratio: float | None,
    numerator_label: str,
    denominator_label: str,
) -> None:
    numerator_title, numerator_rows, denominator_title, denominator_rows = _calculation_details_for_metric(
        data,
        metric,
        numerator,
        denominator,
        numerator_label,
        denominator_label,
    )
    with st.expander(f"Numerator: {numerator_title} = {_format_money_calc(numerator)}", expanded=False):
        _render_calc_rows(numerator_rows)
    with st.expander(f"Denominator: {denominator_title} = {_format_money_calc(denominator)}", expanded=False):
        _render_calc_rows(denominator_rows)
    st.markdown(
        f'<div class="calc-result-line">{html.escape(_result_line(numerator, denominator, ratio))}</div>',
        unsafe_allow_html=True,
    )


def _render_metric_card(title: str, metric: str, threshold: float, questionable_floor: float, numerator_label: str, denominator_label: str, what_it_means: str, why_it_matters: str, note: str = "") -> None:
    data = st.session_state.stock_data or {}
    numerator, denominator, ratio = _metric_data(data, metric)
    core_interest_business = _is_core_interest_business(data)
    status = "unavailable" if core_interest_business else _ratio_status(ratio, threshold, questionable_floor)
    badge = {"pass": _pill("PASS", "pass"), "questionable": _pill("⚠️ BORDERLINE", "questionable"), "fail": _pill("FAIL", "fail"), "unavailable": _pill("N/A", "neutral")}[status]
    ratio_display = "Not applicable" if core_interest_business else _format_ratio(ratio)
    threshold_text = "" if core_interest_business else f"≤ {threshold * 100:.0f}% Threshold"
    if core_interest_business:
        bar_html = '<div class="missing-data">This ratio is not meaningful for banks, insurers, or similar financial businesses.</div>'
    else:
        bar_html = f'<div class="missing-data">{NOT_AVAILABLE}</div>' if ratio is None else _progress_bar_html(ratio * 100, threshold * 100, _ratio_color(status))
    note_html = f'<div class="metric-label">{html.escape(note)}</div>' if note else ""
    disclaimer_html = ""
    if metric == "income":
        fallback_disclaimer = _income_ratio_disclaimer(data)
        if fallback_disclaimer:
            disclaimer_html = f'<div class="metric-label">{html.escape(fallback_disclaimer)}</div>'
    st.markdown(f'''
        <div class="metric-card">
          <div style="display:flex;justify-content:space-between;gap:0.75rem;align-items:flex-start;"><div class="metric-title">{html.escape(title)} <span title="{html.escape(what_it_means)}" style="color:#C9A84C;">?</span></div>{badge}</div>
          <div style="margin-top:0.4rem;"><span class="metric-value">{html.escape(ratio_display)}</span><span class="metric-threshold">{threshold_text}</span></div>
          {bar_html}
          <div class="metric-label"><strong style="color:#F5F5F5;">What it means:</strong><br>{html.escape(what_it_means)}</div>
          <div class="metric-label"><strong style="color:#F5F5F5;">Why it matters:</strong><br>{html.escape(why_it_matters)}</div>{note_html}{disclaimer_html}
        </div>''', unsafe_allow_html=True)
    with st.expander("View Calculation"):
        _render_metric_calculation(
            data,
            metric,
            numerator,
            denominator,
            ratio,
            numerator_label,
            denominator_label,
        )


def _plain_english_financial_summary(data: dict, screening: dict) -> str:
    company = _company_name(data)
    if _is_core_interest_business(data):
        return (
            f"{company} appears to be a bank, insurer, or similar financial business. "
            "Standard debt, cash, and interest-income ratios can be misleading for this business type, "
            "so the business activity screen should drive the result."
        )
    fallback_disclaimer = _income_ratio_disclaimer(data)
    statuses = _financial_statuses(screening)
    failing = [name for name, status in statuses.items() if status == "fail"]
    close = [name for name, status in statuses.items() if status == "questionable"]
    missing = [name for name, status in statuses.items() if status == "unavailable"]
    base_summary: str
    if failing:
        base_summary = f"{company}'s financials exceed the allowed limit for {', '.join(failing)}. That makes the stock fail the financial screen even if other ratios look acceptable."
    elif close:
        base_summary = f"{company}'s financials are mostly within the allowable limits. The {', '.join(close)} ratio is close to its threshold, which makes the result questionable."
    elif missing:
        base_summary = f"{company}'s available financial ratios look acceptable, but some data is missing. Because the available data is incomplete, a scholar should review it before investing."
    else:
        base_summary = f"{company}'s financials are within the allowable limits. Debt, cash, and interest income levels are below the AAOIFI-style thresholds used by this tool."
    if fallback_disclaimer:
        return f"{fallback_disclaimer} {base_summary}"
    return base_summary


def _render_purification_estimator_card(data: dict, screening: dict) -> None:
    stock_status = str((screening or {}).get("result") or "").strip()
    if stock_status == "Not Halal":
        st.markdown(
            (
                '<div class="plain-english"><strong>Purification Not Applicable</strong><br>'
                "This stock has been screened as <strong>Not Halal</strong>. "
                "Purification applies to otherwise permissible investments with a small proportion "
                "of incidental impermissible income. Since this stock does not meet the threshold "
                "for halal compliance, the appropriate step is to avoid holding it rather than to "
                "purify dividends or gains."
                '<br><span style="font-size:12px;color:#888;">For guidance, please consult a qualified Islamic finance scholar.</span>'
                "</div>"
            ),
            unsafe_allow_html=True,
        )
        return
    company = _company_name(data)
    interest_income = _calc_float(data.get("interest_income"))
    _, _, income_ratio = _metric_data(data, "income")
    if (interest_income or 0.0) > 0 and income_ratio is not None and income_ratio > 0:
        ratio_pct = income_ratio * 100
        donation = ratio_pct
        body = (
            f"Because {ratio_pct:.2f}% of {company}'s top-line revenue is derived from interest, "
            f"Shariah standards advise donating ${donation:.2f} out of every $100 you receive in "
            "dividends to purify your income or profit."
        )
    else:
        body = (
            "No interest income was found in the available data. Please review the income statement in detail, "
            "as it is sometimes reported differently, to ensure no purification is needed."
        )
    st.markdown(
        f'<div class="plain-english"><strong>Your Purification Estimator</strong><br>{html.escape(body)}</div>',
        unsafe_allow_html=True,
    )


def _render_methodology_notice_card() -> None:
    st.markdown(
        (
            '<div class="plain-english" style="background-color:#2a2010;border-left:3px solid #a89060;"><strong>Methodology Notice</strong><br>'
            "Note: Calculations can vary compared to other Halal stock screeners depending on the "
            "specific accounting data points they choose to include. Our platform's calculations "
            "strictly adhere to the AAOIFI compliance frameworks.</div>"
        ),
        unsafe_allow_html=True,
    )


def _render_financial_tab(data: dict, screening: dict) -> None:
    _render_metric_card("Debt Ratio", "debt", 0.33, 0.28, "Total Debt", "Market Cap", "Shows how much debt the company carries compared with its market value.", "AAOIFI screening limits excessive debt because it can signal heavy reliance on interest-based financing.")
    _render_metric_card("Interest Income Ratio", "income", 0.05, 0.04, "Interest Income", "Total Revenue", "Shows how much reported income may come from interest compared with total revenue.", "Interest income is monitored because riba is not permissible in Islamic finance.", "Interest income may not be separately reported by all companies.")
    _render_metric_card("Cash & Interest-Bearing Securities Ratio", "cash", 0.33, 0.28, "Total Cash", "Market Cap", "Shows cash and similar holdings compared with the company's market value.", "Large cash or interest-bearing balances can create concern under common halal screening standards.")
    st.markdown(f'<div class="plain-english"><strong>Summary</strong><br>{html.escape(_plain_english_financial_summary(data, screening))}</div>', unsafe_allow_html=True)
    _render_methodology_notice_card()


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    lowered = (text or "").lower()
    for keyword in keywords:
        if keyword in lowered:
            return keyword
    return None


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _ethical_insights_payload(data: dict) -> dict[str, object]:
    raw = data.get("ethical_insights")
    if not isinstance(raw, dict):
        raw = {}
    return {
        "official_bds": _to_bool(raw.get("official_bds")),
        "afsc": _to_bool(raw.get("afsc")),
        "un_ohchr": _to_bool(raw.get("un_ohchr")),
        "who_profits": _to_bool(raw.get("who_profits")),
        "sources_reviewed": raw.get("sources_reviewed"),
    }


def _ethical_flag_count(data: dict) -> int:
    insights = _ethical_insights_payload(data)
    return sum(
        1
        for key in ("official_bds", "afsc", "un_ohchr", "who_profits")
        if insights.get(key)
    )


def _render_ethical_insights_section(data: dict) -> None:
    insights = _ethical_insights_payload(data)
    rows = [
        (
            "Official BDS Target",
            "official_bds",
            "About the BDS Target List",
            """The Boycott, Divestment and Sanctions (BDS) movement is a 
Palestinian-led campaign that calls for economic and political pressure 
related to Israeli government policies toward Palestinians. Companies on 
this list are those the BDS movement has identified as having direct 
involvement in or material support of activities they oppose. This is not 
a legal or regulatory finding. Users should research independently and 
reach their own conclusions based on their values.""",
        ),
        (
            "AFSC Investigate Database",
            "afsc",
            "About AFSC Investigate",
            """The American Friends Service Committee (AFSC) is a Quaker humanitarian 
organization. Their Investigate database tracks companies they identify as 
profiting from military occupation or human rights violations, primarily 
in the context of the Israeli-Palestinian conflict. Inclusion is based on 
AFSC's own research methodology and does not represent a legal or 
regulatory determination. It is one of several civil society tools used 
by ethical investors.""",
        ),
        (
            "UN OHCHR Database",
            "un_ohchr",
            "About the UN OHCHR Database",
            """The United Nations Office of the High Commissioner for Human Rights 
(OHCHR) maintains a database of companies with operations in Israeli 
settlements in the occupied West Bank, including East Jerusalem, as 
mandated by UN Human Rights Council Resolution 31/36. Inclusion means 
the UN has identified a business presence in settlements. This is not a 
sanctions list or legal finding, but is a significant intergovernmental 
reference used by ethical investors worldwide.""",
        ),
        (
            "Who Profits Database",
            "who_profits",
            "About Who Profits",
            """Who Profits is an independent Israeli research center that documents 
commercial involvement in the Israeli military occupation of Palestinian 
and Syrian territories. Their database covers companies involved in 
settlement construction, military supply, natural resource extraction, 
and occupation infrastructure. It is a civil society research tool, not 
a government or regulatory list.""",
        ),
    ]
    st.markdown(
        (
            '<div class="overview-card"><div class="card-title">Ethical Insights</div>'
            '<div class="muted-copy">Educational ethical screening based on publicly available databases.</div></div>'
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <style>
        .ethical-tooltip-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.6rem;
            padding: 10px 0;
        }
        .ethical-tooltip-left {
            display: flex;
            align-items: center;
            gap: 6px;
            min-width: 0;
        }
        .ethical-tooltip-label {
            font-size: 15px;
            color: #ccc;
            line-height: 1.3;
        }
        .tooltip-container {
            position: relative;
            display: inline-block;
            cursor: pointer;
            flex-shrink: 0;
        }
        .tooltip-icon {
            color: #a89060;
            font-size: 15px;
        }
        .tooltip-text {
            visibility: hidden;
            opacity: 0;
            background-color: #1e2d3d;
            color: #ddd;
            font-size: 13px;
            line-height: 1.5;
            border: 1px solid #a89060;
            border-radius: 8px;
            padding: 12px 14px;
            width: 280px;
            position: absolute;
            z-index: 9999;
            left: 20px;
            top: -10px;
            transition: opacity 0.2s;
        }
        .tooltip-container:hover .tooltip-text {
            visibility: visible;
            opacity: 1;
        }
        .badge-clear {
            background-color: #1a6b3a;
            color: #fff;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            white-space: nowrap;
            flex-shrink: 0;
        }
        .badge-listed {
            background-color: #8b1a1a;
            color: #fff;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            white-space: nowrap;
            flex-shrink: 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    for index, (label, key, title, body) in enumerate(rows):
        is_listed = bool(insights.get(key))
        badge_class = "badge-listed" if is_listed else "badge-clear"
        badge_text = "● Listed" if is_listed else "● Clear"
        safe_title = html.escape(title)
        safe_body = html.escape(body.strip()).replace("\n", "<br>")
        st.markdown(
            f"""
            <div class="ethical-tooltip-row">
                <div class="ethical-tooltip-left">
                    <span class="ethical-tooltip-label">{html.escape(label)}</span>
                    <span class="tooltip-container">
                        <span class="tooltip-icon">ⓘ</span>
                        <span class="tooltip-text"><strong>{safe_title}</strong><br><br>{safe_body}</span>
                    </span>
                </div>
                <span class="{badge_class}">{badge_text}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if index < len(rows) - 1:
            st.markdown("<hr class='irizq-divider' style='margin:0.35rem 0 0.4rem 0;'>", unsafe_allow_html=True)

    sources_reviewed = insights.get("sources_reviewed")
    if sources_reviewed is not None:
        st.markdown(
            f'<div class="muted-copy" style="margin-top:0.75rem;">Sources Reviewed: {html.escape(str(sources_reviewed))}</div>',
            unsafe_allow_html=True,
        )


def _render_ethical_insights_tab(data: dict, screening: dict) -> None:
    _render_ethical_insights_section(data)


def _render_news_card(data: dict) -> None:
    news_items = data.get("_ui_news") or []
    if not news_items:
        status = _pill("NO DATA", "neutral")
        body = f'<div class="muted-copy">{NOT_AVAILABLE}</div><div class="muted-copy">No recent news available</div>'
    else:
        flagged_any = False
        items = []
        for item in news_items[:5]:
            headline = item.get("title", "") if isinstance(item, dict) else str(item)
            url = item.get("url", "") if isinstance(item, dict) else ""
            publisher = item.get("publisher", "") if isinstance(item, dict) else ""
            match = _contains_keyword(headline, NEWS_FLAG_KEYWORDS)
            flagged_any = flagged_any or bool(match)
            flag = f'<div class="news-flag">⚠️ Keyword: {html.escape(match)}</div>' if match else ""
            publisher_html = f'<div class="muted-copy" style="font-size:0.76rem;">{html.escape(publisher)}</div>' if publisher else ""
            if url:
                title_html = f'<a href="{html.escape(url)}" target="_blank" style="color:#F5F5F5;text-decoration:none;">{html.escape(headline)}</a>'
            else:
                title_html = html.escape(headline)
            items.append(f'<div class="news-item">{title_html}{publisher_html}{flag}</div>')
        status = _pill("NEWS DETECTED" if flagged_any else "NONE FOUND", "questionable" if flagged_any else "pass")
        body = "".join(items)
    st.markdown(f'<div class="ethical-card"><div class="ethical-card-header"><div class="ethical-title">News Mentions</div>{status}</div>{body}</div>', unsafe_allow_html=True)

def _render_geopolitical_card(profile_text: str) -> None:
    match = _contains_keyword(profile_text, WEAPONS_KEYWORDS)
    status = _pill("POSSIBLE CONCERN", "questionable") if match else _pill("NONE FOUND", "pass")
    concern = f'<div style="color:#F59E0B;margin-top:0.5rem;">Matched keyword: {html.escape(match)}</div>' if match else ""
    st.markdown(f'<div class="ethical-card"><div class="ethical-card-header"><div class="ethical-title">Geopolitical &amp; Weapons</div>{status}</div><div class="muted-copy">⚠️ This is a heuristic check only based on sector classification. Not a verified ethical audit.</div>{concern}</div>', unsafe_allow_html=True)


def _render_israel_connection_card(profile_text: str, data: dict) -> None:
    news_items = data.get("_ui_news") or []
    news_text = " ".join(item.get("title", "") for item in news_items if isinstance(item, dict))
    combined_text = f"{profile_text} {data.get('_ui_info', {}).get('longBusinessSummary', '')} {news_text}"
    match = _contains_keyword(combined_text, ISRAEL_KEYWORDS)
    if match:
        status = _pill("POSSIBLE MENTION", "questionable")
        message = (
            "Available profile or news text mentions "
            f"'{html.escape(match)}'. This may indicate a business location, news event, "
            "partnership, lawsuit, or other mention. It does not prove ownership, support, or a verified ethical connection."
        )
    elif combined_text.strip():
        status = _pill("NONE FOUND", "pass")
        message = "No Israel-related mention was found in the available profile or recent news headlines."
    else:
        status = _pill("NO DATA", "neutral")
        message = "Not available from company profile or recent news headlines."
    st.markdown(f'<div class="ethical-card"><div class="ethical-card-header"><div class="ethical-title">Israel Connection Check</div>{status}</div><div class="muted-copy">{message}</div><div class="muted-copy" style="margin-top:0.5rem;">⚠️ This is a keyword-based check only, not a verified geopolitical audit.</div></div>', unsafe_allow_html=True)

def _render_ethical_tab(data: dict, screening: dict) -> None:
    sector, industry = _format_sector_industry(data.get("sector", ""), data.get("industry", ""))
    profile_text = " ".join(part for part in (sector, industry) if _is_available_text(part))
    prohibited_match = _contains_keyword(profile_text, PROHIBITED_KEYWORDS)
    if not profile_text:
        industry_status, confidence, industry_kind = "UNKNOWN", "Low", "questionable"
    elif prohibited_match:
        industry_status, confidence, industry_kind = "FLAGGED", "Medium", "fail"
    else:
        industry_status, confidence, industry_kind = "CLEAR", "High", "pass"
    st.markdown('''<div class="warning-banner"><strong>⚠️ LIMITED DATA SOURCE</strong><br>Ethical screening below is based only on available market data (sector, industry, company description, and basic news). This is NOT a comprehensive ethical audit. Always consult a qualified Islamic finance scholar.</div>''', unsafe_allow_html=True)
    flag_html = f'<div style="color:#F59E0B;margin-top:0.5rem;">Flagged keyword: {html.escape(prohibited_match)}</div>' if prohibited_match else ""
    st.markdown(f'<div class="ethical-card"><div class="ethical-card-header"><div class="ethical-title">Industry &amp; Sector Assessment</div>{_pill(industry_status, industry_kind)}</div><div class="muted-copy">Sector: {html.escape(sector)}</div><div class="muted-copy">Industry: {html.escape(industry)}</div><div class="muted-copy" style="margin-top:0.5rem;">Confidence level: {html.escape(confidence)}</div>{flag_html}</div>', unsafe_allow_html=True)
    _render_geopolitical_card(profile_text)
    _render_israel_connection_card(profile_text, data)
    _render_news_card(data)


def _render_glossary_card() -> None:
    st.markdown('<div class="overview-card"><div class="card-title">What Do These Terms Mean?</div><div class="muted-copy">Open the glossary below for plain-English definitions.</div></div>', unsafe_allow_html=True)
    with st.expander("Glossary"):
        st.markdown("**Halal / Haram:** Halal means permissible; haram means prohibited under Islamic law.")
        st.markdown("**AAOIFI:** Accounting and Auditing Organization for Islamic Financial Institutions - an international standards body for Islamic finance guidance.")
        st.markdown("**Debt Ratio:** Total debt divided by market capitalization.")
        st.markdown("**Interest Income:** Money earned from interest-bearing sources.")
        st.markdown("**Riba:** Interest or usury, which is prohibited in Islamic finance.")
        st.markdown("**Market Cap:** The total market value of a company's shares.")


def _render_details_tab(data: dict, screening: dict) -> None:
    st.markdown(
        """
  <div style="
    background-color: #1A2B3C;
    border-radius: 12px;
    padding: 1.4rem 1.6rem;
    margin: 0 0 1.2rem 0;
    border: 1px solid #2A3F55;
    border-left: 4px solid #C9A84C;
  ">
    <div style="
      color: #C9A84C;
      font-family: 'Inter', sans-serif;
      font-weight: 700;
      font-size: 1.1rem;
      margin-bottom: 0.2rem;
    ">
      Why AAOIFI Standard?
    </div>
    <div style="
      color: #8A9BB0;
      font-family: 'Inter', sans-serif;
      font-size: 0.82rem;
      margin-bottom: 1.2rem;
    ">
      The global benchmark for Islamic finance screening
    </div>

    <!-- Bullet 1 -->
    <div style="
      display: flex;
      gap: 0.8rem;
      margin-bottom: 1rem;
      align-items: flex-start;
    ">
      <span style="font-size: 1.2rem; line-height: 1;">🌍</span>
      <div>
        <div style="
          color: #F5F5F5;
          font-family: 'Inter', sans-serif;
          font-weight: 600;
          font-size: 0.92rem;
          margin-bottom: 0.2rem;
        ">Used in 45+ countries worldwide</div>
        <div style="
          color: #8A9BB0;
          font-family: 'Inter', sans-serif;
          font-size: 0.85rem;
          line-height: 1.5;
        ">AAOIFI standards are adopted by regulators, financial
        institutions, and Islamic banks across 45+ countries
        including Bahrain, UAE, Pakistan, Sudan, and Malaysia.</div>
      </div>
    </div>

    <!-- Bullet 2 -->
    <div style="
      display: flex;
      gap: 0.8rem;
      margin-bottom: 1rem;
      align-items: flex-start;
    ">
      <span style="font-size: 1.2rem; line-height: 1;">👨‍🏫</span>
      <div>
        <div style="
          color: #F5F5F5;
          font-family: 'Inter', sans-serif;
          font-weight: 600;
          font-size: 0.92rem;
          margin-bottom: 0.2rem;
        ">Defined by leading Islamic finance scholars</div>
        <div style="
          color: #8A9BB0;
          font-family: 'Inter', sans-serif;
          font-size: 0.85rem;
          line-height: 1.5;
        ">Developed and maintained by an international board of
        recognized Shariah scholars with decades of expertise in
        Islamic jurisprudence and modern finance.</div>
      </div>
    </div>

    <!-- Bullet 3 -->
    <div style="
      display: flex;
      gap: 0.8rem;
      margin-bottom: 1rem;
      align-items: flex-start;
    ">
      <span style="font-size: 1.2rem; line-height: 1;">🏆</span>
      <div>
        <div style="
          color: #F5F5F5;
          font-family: 'Inter', sans-serif;
          font-weight: 600;
          font-size: 0.92rem;
          margin-bottom: 0.2rem;
        ">Most widely used standard in the Islamic world</div>
        <div style="
          color: #8A9BB0;
          font-family: 'Inter', sans-serif;
          font-size: 0.85rem;
          line-height: 1.5;
        ">The most broadly accepted halal screening methodology
        globally, making it the most relevant choice for Muslim
        investors anywhere in the world.</div>
      </div>
    </div>

    <!-- Bullet 4 -->
    <div style="
      display: flex;
      gap: 0.8rem;
      margin-bottom: 1rem;
      align-items: flex-start;
    ">
      <span style="font-size: 1.2rem; line-height: 1;">🔒</span>
      <div>
        <div style="
          color: #F5F5F5;
          font-family: 'Inter', sans-serif;
          font-weight: 600;
          font-size: 0.92rem;
          margin-bottom: 0.2rem;
        ">Among the most rigorous and restrictive</div>
        <div style="
          color: #8A9BB0;
          font-family: 'Inter', sans-serif;
          font-size: 0.85rem;
          line-height: 1.5;
        ">Applies strict financial thresholds — 33% debt ratio
        and 5% non-permissible income limit — making it one of
        the most conservative and trustworthy screening
        frameworks available.</div>
      </div>
    </div>

    <!-- Bullet 5 -->
    <div style="
      display: flex;
      gap: 0.8rem;
      align-items: flex-start;
    ">
      <span style="font-size: 1.2rem; line-height: 1;">📜</span>
      <div>
        <div style="
          color: #F5F5F5;
          font-family: 'Inter', sans-serif;
          font-weight: 600;
          font-size: 0.92rem;
          margin-bottom: 0.2rem;
        ">Recognized by major Islamic financial institutions</div>
        <div style="
          color: #8A9BB0;
          font-family: 'Inter', sans-serif;
          font-size: 0.85rem;
          line-height: 1.5;
        ">Adopted by hundreds of Islamic banks, takaful operators,
        and investment firms worldwide as the gold standard for
        Shariah-compliant finance.</div>
      </div>
    </div>

  </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('''<div class="overview-card"><div class="card-title">How iRizq Screens Stocks</div><div class="muted-copy">iRizq applies an AAOIFI-style screen using available business activity information and financial ratios such as debt, cash, and income ratios. This app uses available market data only, so results are educational and should be reviewed with qualified guidance.</div><div style="margin-top:0.7rem;"><a href="https://aaoifi.com" target="_blank" style="color:#C9A84C;text-decoration:none;">Learn more about AAOIFI standards →</a></div></div>''', unsafe_allow_html=True)
    st.markdown('''<div class="overview-card"><div class="card-title">Data Sources Used</div><div class="muted-copy">✅ SEC 10-K / 10-Q filings</div><div class="muted-copy">✅ SEC XBRL company facts</div><div class="muted-copy">✅ Company profile (cached)</div><div class="muted-copy">✅ Income statement (normalized)</div><div class="muted-copy">✅ Balance sheet (normalized)</div></div>''', unsafe_allow_html=True)
    st.markdown('''<div class="overview-card"><div class="card-title">What is NOT Included</div><div class="muted-copy">❌ Segment revenue breakdowns</div><div class="muted-copy">❌ Subsidiary analysis</div><div class="muted-copy">❌ Verified geopolitical data</div><div class="muted-copy">❌ ESG scores</div><div class="muted-copy">❌ Shariah board certifications</div><div class="muted-copy">❌ Personalized fatwa guidance</div></div>''', unsafe_allow_html=True)
    debt_num, debt_den, debt_ratio = _metric_data(data, "debt")
    cash_num, cash_den, cash_ratio = _metric_data(data, "cash")
    income_num, income_den, income_ratio = _metric_data(data, "income")
    st.markdown(f'<div class="overview-card"><div class="card-title">Calculation Breakdown</div><div class="muted-copy">Debt Ratio = {_format_money(debt_num)} ÷ {_format_money(debt_den)} = {_format_ratio(debt_ratio)}</div><div class="muted-copy">Cash Ratio = {_format_money(cash_num)} ÷ {_format_money(cash_den)} = {_format_ratio(cash_ratio)}</div><div class="muted-copy">Income Ratio = {_format_money(income_num)} ÷ {_format_money(income_den)} = {_format_ratio(income_ratio)}</div></div>', unsafe_allow_html=True)
    _render_glossary_card()
    render_disclaimer()
    render_feedback()

def render_results(data: dict, screening: dict) -> None:
    # Streamlit tabs keep their selected index across reruns. Changing the
    # invisible suffix after a new screen remounts the tabs back to Overview.
    reset_suffix = "​" * int(st.session_state.get("tabs_reset_token", 0))
    tab1, tab2, tab3, tab4 = st.tabs([
        f"Overview{reset_suffix}",
        f"Financial{reset_suffix}",
        f"Ethical{reset_suffix}",
        f"Guide{reset_suffix}",
    ])
    with tab1:
        _render_overview_tab(data, screening)
    with tab2:
        _render_financial_tab(data, screening)
    with tab3:
        _render_ethical_insights_tab(data, screening)
    with tab4:
        _render_details_tab(data, screening)


def render_error(
    ticker: str,
    transient: bool = False,
    database_unavailable: bool = False,
    cache_missing: bool = False,
) -> None:
    if database_unavailable:
        message = (
            "Local SEC database is currently unavailable. "
            "Please verify <strong>DATABASE_URL</strong> and database connectivity."
        )
    elif cache_missing:
        message = (
            f"Recent SEC data is currently unavailable for <strong>{ticker.upper()}</strong>. "
            "This ticker may not have a recent 10-Q/10-K filing or SEC company-facts coverage yet."
        )
    elif transient:
        message = (
            f"Market data for <strong>{ticker.upper()}</strong> is temporarily unavailable "
            "(data refresh or network issue). Wait 10-20 seconds and click "
            "<strong>Check Status</strong> again."
        )
    else:
        message = (
            f"Could not retrieve data for <strong>{ticker.upper()}</strong>. "
            "Please check the symbol and try again."
        )
    st.markdown(
        f'<div class="error-card">{message}</div>',
        unsafe_allow_html=True,
    )


def render_feedback() -> None:
    st.markdown(
        """
        <div style="
            background-color: #1A2B3C;
            border: 1px solid #2A3F55;
            border-left: 4px solid #C9A84C;
            border-radius: 10px;
            padding: 1rem 1.5rem;
            margin: 1.5rem 0;
            text-align: center;
        ">
            <p style="
                color: #F5F5F5;
                font-family: 'Inter', sans-serif;
                font-size: 0.95rem;
                font-weight: 600;
                margin: 0 0 0.5rem 0;
            ">
                🌟 Help us improve this tool!
            </p>
            <p style="
                color: #8A9BB0;
                font-family: 'Inter', sans-serif;
                font-size: 0.85rem;
                margin: 0 0 1rem 0;
            ">
                This is a beta version. Your feedback helps us
                build a better halal investing experience.
            </p>
            <a href="https://forms.gle/Jn9xzW46hPT43SSz6" target="_blank" style="
                background-color: #C9A84C;
                color: #0D1B2A;
                font-family: 'Inter', sans-serif;
                font-weight: 700;
                font-size: 0.9rem;
                padding: 0.5rem 1.5rem;
                border-radius: 20px;
                text-decoration: none;
                display: inline-block;
            ">
                📝 Share Your Feedback
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_feedback_small() -> None:
    st.markdown(
        """
        <div style="text-align: center; padding: 1rem 0; margin-top: 0.5rem;">
            <a href="https://forms.gle/Jn9xzW46hPT43SSz6" target="_blank" style="
                color: #8A9BB0;
                font-family: 'Inter', sans-serif;
                font-size: 0.82rem;
                text-decoration: none;
                border-bottom: 1px dashed #2A3F55;
            ">
                ⭐ Rate this tool &amp; share feedback
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_aaoifi_box() -> None:
    st.markdown(
        """
        <div class="aaoifi-info-box">
          <details>
            <summary>What is AAOIFI?</summary>
            <div class="aaoifi-info-copy">
              AAOIFI stands for <strong>Accounting and Auditing Organization for Islamic Financial Institutions</strong>.
            </div>
          </details>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_whatsapp_share(data: dict, screening: dict) -> None:
    symbol = str(data.get("symbol", "")).upper()
    company = _company_name(data)
    result = _display_result(data, screening)
    share_text = (
        f"I checked {company} ({symbol}) on iRizq Halal Stock checker.\n\n"
        f"Result: {result}\n\n"
        "For details, visit https://stocks.irizq.com"
    )
    url = f"https://wa.me/?text={quote(share_text)}"
    st.markdown(f'''
        <div style="text-align:center;margin:1rem 0;">
          <a href="{url}" target="_blank" style="
            background-color:#25D366;color:#0D1B2A;font-weight:800;
            padding:0.65rem 1.2rem;border-radius:999px;text-decoration:none;
            display:inline-block;font-family:'Inter',sans-serif;
          ">Share on WhatsApp</a>
        </div>
        ''', unsafe_allow_html=True)


def _filter_local_stock_candidates(raw_query: str) -> list[dict[str, str]]:
    rows = _search_stocks_rows(raw_query, limit=10)
    return [{"ticker": ticker, "company_name": company_name} for ticker, company_name in rows]


def _find_exact_local_match(raw_query: str) -> dict[str, str] | None:
    query = (raw_query or "").strip().lower()
    if not query:
        return None
    rows = _search_stocks_rows(raw_query, limit=10)
    for ticker, company_name in rows:
        if query == ticker.lower() or query == (company_name or "").lower():
            return {"ticker": ticker, "company_name": company_name}
    return None


def _resolve_ticker_from_search_query(raw_query: str) -> str | None:
    exact = _find_exact_local_match(raw_query)
    if exact:
        return exact["ticker"]
    candidates = _filter_local_stock_candidates(raw_query)
    if not candidates:
        return None
    return candidates[0]["ticker"]


def _searchbox_local_stock_options(search_query: str) -> list[tuple[str, str]]:
    matches = _search_stocks_rows(search_query, limit=10)
    return [
        (f"{ticker} — {company_name}" if company_name else ticker, ticker)
        for ticker, company_name in matches
    ]


def _sync_autocomplete_state(raw_query: str) -> None:
    query = (raw_query or "").strip()
    if not query:
        st.session_state.filtered_results = []
        st.session_state.is_dropdown_open = False
        return
    exact = _find_exact_local_match(query)
    if (
        exact
        and st.session_state.get("has_results")
        and st.session_state.get("last_ticker") == exact["ticker"]
    ):
        st.session_state.filtered_results = []
        st.session_state.is_dropdown_open = False
        return
    filtered = _filter_local_stock_candidates(query)
    st.session_state.filtered_results = filtered
    st.session_state.is_dropdown_open = True


def _select_ticker_from_autocomplete(ticker: str) -> None:
    selected = (ticker or "").strip().upper()
    if not selected:
        return
    st.session_state.resolved_ticker = selected
    st.session_state.pending_selection_ticker = selected
    st.session_state.ticker_input_prefill = selected
    st.session_state.is_dropdown_open = False
    st.session_state.filtered_results = []
    st.rerun()


def _on_search_input_change() -> None:
    raw = str(st.session_state.get("ticker_input_widget", "") or "")
    st.session_state.ticker_input = raw
    _sync_autocomplete_state(raw)


def _render_autocomplete_dropdown() -> None:
    if not st.session_state.get("is_dropdown_open"):
        return
    filtered = st.session_state.get("filtered_results") or []
    suggestion_count = max(len(filtered), 1)
    spacer_height_rem = min(16.0, max(4.1, 3.1 * suggestion_count))
    st.markdown('<div class="autocomplete-anchor"><div class="autocomplete-dropdown">', unsafe_allow_html=True)
    if filtered:
        for stock in filtered:
            ticker = stock["ticker"]
            company_name = stock["company_name"]
            if st.button(
                f"{ticker}\n",
                key=f"autocomplete_select_{ticker}",
                use_container_width=True,
            ):
                _select_ticker_from_autocomplete(ticker)
            st.markdown(
                f'<div class="autocomplete-item-name">{html.escape(company_name)}</div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div class="autocomplete-empty">No matches in the current local stock universe.</div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        '</div></div>'
        f'<div class="autocomplete-spacer" style="height:{spacer_height_rem:.2f}rem;"></div>',
        unsafe_allow_html=True,
    )


def initialize_session_state() -> None:
    defaults = {
        "stock_data": None,
        "screening": None,
        "last_ticker": "",
        "ticker_input": "",
        "ticker_input_widget": "",
        "ticker_input_prefill": "",
        "filtered_results": [],
        "is_dropdown_open": False,
        "resolved_ticker": "",
        "pending_selection_ticker": "",
        "tabs_reset_token": 0,
        "has_results": False,
        "admin_authenticated": False,
        "analytics_uid": "",
        "analytics_visit_tracked": False,
        "analytics_table_ready": False,
        "analytics_error": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_results_for_error(ticker: str) -> None:
    st.session_state.stock_data = None
    st.session_state.screening = None
    st.session_state.last_ticker = ticker
    st.session_state.has_results = False


def run_screening_flow(ticker: str, *, refresh: bool = False) -> None:
    if refresh:
        fetch_stock_data_cached.clear()
        fetch_ui_enrichment_cached.clear()

    progress_bar = st.progress(0)
    status_text = st.empty()

    try:
        status_text.markdown("🔍 Looking up company profile...")
        progress_bar.progress(20)
        time.sleep(0.3)

        status_text.markdown("📊 Fetching financial statements...")
        progress_bar.progress(50)
        if ticker.upper() in FORCE_REFRESH_TICKERS:
            print(f"[TEST MODE] Bypassing cache for {ticker} — fresh fetch")
            st.info(
                f"🔄 **Test Mode:** Fetching fresh data for {ticker}. "
                "Remove FORCE_REFRESH_TICKERS entry after verification.",
                icon="🧪"
            )
            stock_data = _fetch_stock_data(ticker)
            enrichment = _fetch_company_enrichment(ticker)
        else:
            stock_data = fetch_stock_data_cached(ticker)
            enrichment = fetch_ui_enrichment_cached(ticker)

        if stock_data is None or stock_data.get("error"):
            clear_results_for_error(ticker)
            render_error(ticker)
            return

        status_text.markdown("🧮 Running AAOIFI screening...")
        progress_bar.progress(80)
        screening = screen_stock(stock_data)

        st.session_state.stock_data = _build_enriched_stock_data(stock_data, enrichment)
        st.session_state.screening = screening
        st.session_state.last_ticker = ticker
        st.session_state.tabs_reset_token += 1
        st.session_state.has_results = True

        status_text.markdown("✅ Done!")
        progress_bar.progress(100)
        time.sleep(0.3)
    except CachedDataNotReadyError:
        clear_results_for_error(ticker)
        render_error(ticker, cache_missing=True)
    except DatabaseUnavailableError:
        fetch_stock_data_cached.clear()
        clear_results_for_error(ticker)
        render_error(ticker, database_unavailable=True)
    except TransientDataError:
        fetch_stock_data_cached.clear()
        clear_results_for_error(ticker)
        render_error(ticker, transient=True)
    except Exception:
        clear_results_for_error(ticker)
        render_error(ticker)
    finally:
        progress_bar.empty()
        status_text.empty()


def _query_param_value(name: str) -> str:
    raw = st.query_params.get(name, "")
    if isinstance(raw, list):
        return str(raw[0] if raw else "").strip()
    return str(raw or "").strip()


def _analytics_source_from_page() -> str:
    utm_source = _query_param_value("utm_source")
    return infer_source(utm_source or None, None)


def _analytics_uid() -> str:
    uid = str(st.session_state.get("analytics_uid") or "").strip()
    if uid:
        return uid
    uid = str(uuid.uuid4())
    st.session_state.analytics_uid = uid
    return uid


def _ensure_analytics_table_once() -> None:
    if st.session_state.get("analytics_table_ready"):
        return
    try:
        ensure_events_table()
        st.session_state.analytics_table_ready = True
        st.session_state.analytics_error = ""
    except Exception:
        st.session_state.analytics_error = "Analytics database is unavailable."


def _track_streamlit_event(event_type: str, *, ticker: str | None = None) -> None:
    _ensure_analytics_table_once()
    if st.session_state.get("analytics_error"):
        return
    try:
        track_event(
            event_type=event_type,
            user_id=_analytics_uid(),
            ticker=ticker,
            source=_analytics_source_from_page(),
        )
    except Exception:
        st.session_state.analytics_error = "Analytics tracking is temporarily unavailable."


def _normalize_database_url_for_psycopg2(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url[len("postgresql+psycopg2://") :]
    return url


def _streamlit_admin_time_window() -> tuple[datetime.datetime, datetime.datetime, str, str, str, str | None]:
    now = datetime.datetime.utcnow()
    selected_range = _query_param_value("range").lower()
    start_param = _query_param_value("start")
    end_param = _query_param_value("end")

    def _parse_date(raw: str) -> date | None:
        try:
            return date.fromisoformat((raw or "").strip())
        except ValueError:
            return None

    filter_error: str | None = None
    if selected_range == "custom" or start_param or end_param:
        start_date = _parse_date(start_param)
        end_date = _parse_date(end_param)
        if start_date is None or end_date is None:
            filter_error = "Invalid custom range. Showing last 7 days."
        elif end_date < start_date:
            filter_error = "End date must be on or after start date. Showing last 7 days."
        else:
            return (
                datetime.datetime.combine(start_date, datetime.time.min),
                datetime.datetime.combine(end_date, datetime.time.max),
                "custom",
                start_date.isoformat(),
                end_date.isoformat(),
                None,
            )

    active_range = selected_range if selected_range in {"24h", "7d", "30d"} else "7d"
    if active_range == "24h":
        start_ts = now - datetime.timedelta(hours=24)
    elif active_range == "30d":
        start_ts = now - datetime.timedelta(days=30)
    else:
        active_range = "7d"
        start_ts = now - datetime.timedelta(days=7)
    return (
        start_ts,
        now,
        active_range,
        start_ts.date().isoformat(),
        now.date().isoformat(),
        filter_error,
    )


def _set_streamlit_admin_filter(range_value: str, *, start: str | None = None, end: str | None = None) -> None:
    st.query_params.clear()
    st.query_params["page"] = "admin"
    st.query_params["range"] = range_value
    if start and end:
        st.query_params["start"] = start
        st.query_params["end"] = end
    st.rerun()


def _query_streamlit_admin_stats(start_ts: datetime.datetime, end_ts: datetime.datetime) -> dict[str, object]:
    dsn = _normalize_database_url_for_psycopg2(settings.database_url)
    parsed = urlparse(dsn)
    connect_kwargs: dict[str, object] = {"connect_timeout": 10}
    hostname = (parsed.hostname or "").lower()
    if hostname and hostname not in {"localhost", "127.0.0.1"}:
        connect_kwargs["sslmode"] = settings.analytics_sslmode

    conn = psycopg2.connect(dsn, **connect_kwargs)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM events
                WHERE event_type = %s
                AND timestamp >= %s AND timestamp <= %s
                """,
                ("visit", start_ts, end_ts),
            )
            total_visits = int((cur.fetchone() or [0])[0] or 0)

            cur.execute(
                """
                SELECT COUNT(*)
                FROM events
                WHERE event_type = %s
                AND timestamp >= %s AND timestamp <= %s
                """,
                ("search", start_ts, end_ts),
            )
            total_searches = int((cur.fetchone() or [0])[0] or 0)

            cur.execute(
                """
                SELECT COUNT(DISTINCT user_id)
                FROM events
                WHERE timestamp >= %s AND timestamp <= %s
                """,
                (start_ts, end_ts),
            )
            unique_users = int((cur.fetchone() or [0])[0] or 0)

            cur.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT user_id
                    FROM events
                    WHERE timestamp >= %s AND timestamp <= %s
                    GROUP BY user_id
                    HAVING COUNT(*) > 1
                ) AS returning_users
                """,
                (start_ts, end_ts),
            )
            return_users = int((cur.fetchone() or [0])[0] or 0)

            cur.execute(
                """
                SELECT ticker, COUNT(*) AS search_count
                FROM events
                WHERE event_type = %s
                AND timestamp >= %s AND timestamp <= %s
                AND ticker IS NOT NULL AND ticker <> ''
                GROUP BY ticker
                ORDER BY search_count DESC, ticker ASC
                LIMIT 10
                """,
                ("search", start_ts, end_ts),
            )
            top_tickers = [
                {"ticker": str(row[0]), "search_count": int(row[1])}
                for row in (cur.fetchall() or [])
            ]

            cur.execute(
                """
                SELECT COALESCE(NULLIF(source, ''), 'direct') AS source_label, COUNT(*) AS event_count
                FROM events
                WHERE timestamp >= %s AND timestamp <= %s
                GROUP BY COALESCE(NULLIF(source, ''), 'direct')
                ORDER BY event_count DESC, source_label ASC
                """,
                (start_ts, end_ts),
            )
            traffic_sources = [
                {"source": str(row[0]), "count": int(row[1])}
                for row in (cur.fetchall() or [])
            ]

            cur.execute(
                """
                SELECT DATE(timestamp), COUNT(*)
                FROM events
                WHERE event_type = 'search'
                AND timestamp >= %s AND timestamp <= %s
                GROUP BY DATE(timestamp)
                ORDER BY DATE(timestamp) ASC
                """,
                (start_ts, end_ts),
            )
            searches_per_day = [
                {
                    "date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                    "count": int(row[1]),
                }
                for row in (cur.fetchall() or [])
            ]

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT event_type, user_id, ticker, COALESCE(NULLIF(source, ''), 'direct') AS source, timestamp
                FROM events
                WHERE timestamp >= %s AND timestamp <= %s
                ORDER BY timestamp DESC
                LIMIT 50
                """,
                (start_ts, end_ts),
            )
            rows = cur.fetchall() or []
            last_events: list[dict[str, object]] = []
            for row in rows:
                last_events.append(
                    {
                        "event_type": str(row.get("event_type") or ""),
                        "user_id": str(row.get("user_id") or ""),
                        "ticker": row.get("ticker"),
                        "source": str(row.get("source") or "direct"),
                        "timestamp": row.get("timestamp"),
                    }
                )
    finally:
        conn.close()

    conversion_rate = (total_searches / total_visits) if total_visits > 0 else 0.0
    return {
        "total_visits": total_visits,
        "total_searches": total_searches,
        "unique_users": unique_users,
        "return_users": return_users,
        "top_tickers": top_tickers,
        "traffic_sources": traffic_sources,
        "conversion_rate": conversion_rate,
        "last_events": last_events,
        "searches_per_day": searches_per_day,
    }


def _render_streamlit_admin_page() -> None:
    st.markdown("## Internal Analytics Dashboard")
    st.caption("Secure admin view rendered directly inside Streamlit.")

    if st.button("Back to Stock Checker", use_container_width=True):
        st.query_params.clear()
        st.rerun()

    _ensure_analytics_table_once()
    if st.session_state.get("analytics_error"):
        st.error(st.session_state.analytics_error)
        return

    def _normalize_password(raw: object) -> str:
        return str(raw or "").strip().strip('"').strip("'")

    def _resolved_admin_password() -> tuple[str, str]:
        candidates: list[tuple[str, object]] = []
        try:
            candidates.extend(
                [
                    ("st.secrets.ANALYTICS_ADMIN_PASSWORD", st.secrets.get("ANALYTICS_ADMIN_PASSWORD")),
                    ("st.secrets.analytics_admin_password", st.secrets.get("analytics_admin_password")),
                ]
            )
            analytics_block = st.secrets.get("analytics")
            if hasattr(analytics_block, "get"):
                candidates.extend(
                    [
                        ("st.secrets.analytics.admin_password", analytics_block.get("admin_password")),
                        ("st.secrets.analytics.password", analytics_block.get("password")),
                    ]
                )
        except Exception:
            pass

        candidates.extend(
            [
                ("os.getenv(ANALYTICS_ADMIN_PASSWORD)", os.getenv("ANALYTICS_ADMIN_PASSWORD")),
                ("config.settings.analytics_admin_password", settings.analytics_admin_password),
            ]
        )

        for source, raw in candidates:
            normalized = _normalize_password(raw)
            if normalized and normalized != "change-me":
                return normalized, source
        return "change-me", "default-fallback"

    expected_password, password_source = _resolved_admin_password()
    if expected_password == "change-me":
        st.warning(
            "Admin password is still using default fallback. "
            "Set ANALYTICS_ADMIN_PASSWORD in Streamlit Secrets or environment variables, then restart app."
        )
    st.caption(f"Password source detected: {password_source}")

    if not st.session_state.get("admin_authenticated"):
        password = st.text_input("Admin Password", type="password", key="admin_password_input")
        if st.button("Login to Admin", type="primary", use_container_width=True):
            entered = _normalize_password(password)
            if entered and entered == expected_password:
                st.session_state.admin_authenticated = True
                st.rerun()
            else:
                st.error("Invalid admin password.")
        return

    col_logout, col_refresh = st.columns(2)
    with col_logout:
        if st.button("Logout", use_container_width=True):
            st.session_state.admin_authenticated = False
            st.rerun()
    with col_refresh:
        if st.button("Refresh Stats", use_container_width=True):
            st.rerun()

    start_ts, end_ts, active_range, custom_start, custom_end, filter_error = _streamlit_admin_time_window()
    st.markdown("### Date Filter")
    f1, f2, f3 = st.columns(3)
    with f1:
        if st.button(
            "Last 24 hours",
            type="primary" if active_range == "24h" else "secondary",
            use_container_width=True,
        ):
            _set_streamlit_admin_filter("24h")
    with f2:
        if st.button(
            "Last 7 days",
            type="primary" if active_range == "7d" else "secondary",
            use_container_width=True,
        ):
            _set_streamlit_admin_filter("7d")
    with f3:
        if st.button(
            "Last 30 days",
            type="primary" if active_range == "30d" else "secondary",
            use_container_width=True,
        ):
            _set_streamlit_admin_filter("30d")

    with st.form("admin-custom-range-form"):
        c_start, c_end = st.columns(2)
        with c_start:
            start_date = st.date_input("Start date", value=date.fromisoformat(custom_start), key="admin_custom_start")
        with c_end:
            end_date = st.date_input("End date", value=date.fromisoformat(custom_end), key="admin_custom_end")
        submitted = st.form_submit_button("Apply Custom Range", use_container_width=True)
        if submitted:
            _set_streamlit_admin_filter(
                "custom",
                start=start_date.isoformat(),
                end=end_date.isoformat(),
            )

    st.caption(
        f"Active window: {start_ts.strftime('%Y-%m-%d %H:%M:%S UTC')} to {end_ts.strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
    if filter_error:
        st.warning(filter_error)

    try:
        stats = _query_streamlit_admin_stats(start_ts, end_ts)
    except Exception:
        st.error("Failed to load analytics metrics from database.")
        return

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Visits", stats.get("total_visits", 0))
    c2.metric("Total Searches", stats.get("total_searches", 0))
    c3.metric("Unique Users", stats.get("unique_users", 0))
    c4.metric("Return Users", stats.get("return_users", 0))
    c5.metric("Conversion", f"{(stats.get('conversion_rate', 0.0) * 100):.2f}%")

    st.markdown("### Searches per Day")
    searches_per_day = stats.get("searches_per_day") or []
    if searches_per_day:
        chart_df = pd.DataFrame(searches_per_day)
        chart_df = chart_df.rename(columns={"count": "searches"}).set_index("date")
        st.bar_chart(chart_df)
    else:
        st.info("No search events found for selected date range.")

    st.markdown("### Most Searched Tickers")
    top_tickers = stats.get("top_tickers") or []
    st.table(top_tickers if top_tickers else [{"ticker": "-", "search_count": 0}])

    st.markdown("### Traffic Sources")
    traffic_sources = stats.get("traffic_sources") or []
    st.table(traffic_sources if traffic_sources else [{"source": "direct", "count": 0}])

    st.markdown("### Last 50 Events")
    last_events = stats.get("last_events") or []
    st.dataframe(last_events, use_container_width=True)

def main() -> None:
    st.set_page_config(
        page_title="Halal Stock Checker | iRizq",
        page_icon="static/icon.png",
        layout="centered",
    )

    initialize_session_state()
    inject_head_and_styles()
    _ensure_analytics_table_once()
    ensure_search_index()

    requested_page = _query_param_value("page").lower()
    if requested_page == "admin":
        _render_streamlit_admin_page()
        return

    if not st.session_state.get("analytics_visit_tracked"):
        _track_streamlit_event("visit")
        st.session_state.analytics_visit_tracked = True

    logo_path = "static/icon.png" if os.path.exists("static/icon.png") else "static/logo.png"
    if os.path.exists(logo_path):
        st.markdown(_app_header_html(logo_path), unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="app-header">'
            '<div class="app-header-title">Halal Stock Checker</div>'
            '<div class="app-header-subtitle">AAOIFI-Based Screening Powered by '
            '<a href="https://www.iRizq.com" target="_blank">iRizq.com</a></div>'
            '</div>',
            unsafe_allow_html=True,
        )

    selected = st_searchbox(
        search_function=_searchbox_local_stock_options,
        label="Search by Ticker or Company Name:",
        placeholder="e.g. AAPL or Apple Inc.",
        key="stock_searchbox",
        clear_on_submit=False,
        debounce=300,
    )
    st.markdown(
        "<p style='font-size: 12px; color: #888; margin-top: -10px;'>"
        "Screens US-listed stocks only. ETFs, index funds, and foreign "
        "stocks are not supported.</p>",
        unsafe_allow_html=True
    )
    search_query = str(selected or "").strip()
    if selected:
        st.session_state.resolved_ticker = search_query
    st.session_state.ticker_input = search_query

    check_clicked = st.button("Check Status", type="primary", use_container_width=True)

    if check_clicked:
        st.session_state.is_dropdown_open = False
        st.session_state.filtered_results = []
        if not search_query:
            st.markdown(
                '<div class="info-msg">Please enter a stock ticker or company name to continue.</div>',
                unsafe_allow_html=True,
            )
        else:
            resolved_ticker = _resolve_ticker_from_search_query(search_query)
            st.session_state.resolved_ticker = resolved_ticker or ""
            if not resolved_ticker:
                st.markdown(
                    '<div class="info-msg">No matching stock was found in the database. '
                    "Please try a different ticker or company name.</div>",
                    unsafe_allow_html=True,
                )
            else:
                _track_streamlit_event("search", ticker=resolved_ticker)
            if resolved_ticker and (
                resolved_ticker != st.session_state.last_ticker
                or not st.session_state.has_results
            ):
                run_screening_flow(resolved_ticker)
            elif resolved_ticker:
                st.markdown(
                    '<div class="info-msg">Showing saved results. Enter a different ticker and click Check Status to run a new screen.</div>',
                    unsafe_allow_html=True,
                )


    if st.session_state.has_results and st.session_state.stock_data and st.session_state.screening:
        render_results(st.session_state.stock_data, st.session_state.screening)
        render_whatsapp_share(st.session_state.stock_data, st.session_state.screening)
    elif not st.session_state.has_results:
        render_disclaimer()

    render_aaoifi_box()
    render_feedback_small()
    st.markdown(
        "<div style='margin-top: 10px; text-align: center;'>"
        "<a href='?page=admin' style='font-size: 12px; color: #6b7280;'>Admin Dashboard</a>"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
