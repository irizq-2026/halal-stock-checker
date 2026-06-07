"""Halal Stock Checker (iRizq.com) - Streamlit UI."""

from __future__ import annotations

import base64
import html
import os
import time
from datetime import date
from urllib.parse import quote, urlparse

import streamlit as st

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
      max-width: 33.33% !important;
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
          <div class="muted-copy" style="margin-top:0.8rem;">Last Updated: {html.escape(date.today().strftime("%B %d, %Y"))}</div>
        </div>
        ''', unsafe_allow_html=True)
    _render_at_a_glance(data, screening)
    _render_quick_summary(data, screening)

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
    rows = [("Business Activity", _pill("HALAL" if business_kind == "pass" else "NOT HALAL" if business_kind == "fail" else "QUESTIONABLE", business_kind)), ("Financial Screening", _pill(financial_label, financial_kind)), ("Ethical Filters", _pill("LIMITED", "limited")), ("Overall", _status_badge(_display_result(data, screening)))]
    body = "".join(f'<div class="glance-row"><span class="glance-label">{html.escape(label)}</span>{badge}</div>' for label, badge in rows)
    st.markdown(f'<div class="overview-card"><div class="card-title">At a Glance</div>{body}</div>', unsafe_allow_html=True)

def _metric_data(data: dict, metric: str) -> tuple[float | None, float | None, float | None]:
    if _is_core_interest_business(data):
        if metric == "debt":
            return data.get("total_debt"), data.get("market_cap"), None
        if metric == "cash":
            return data.get("cash"), data.get("market_cap"), None
        return data.get("interest_income"), data.get("total_revenue"), None

    if metric == "debt":
        numerator, denominator = data.get("total_debt"), data.get("market_cap")
    elif metric == "cash":
        numerator, denominator = data.get("cash"), data.get("market_cap")
    else:
        numerator, denominator = data.get("interest_income"), data.get("total_revenue")
    if numerator is None or denominator in (None, 0):
        return numerator, denominator, None
    try:
        return float(numerator), float(denominator), float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError):
        return numerator, denominator, None


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
    st.markdown(f'''
        <div class="metric-card">
          <div style="display:flex;justify-content:space-between;gap:0.75rem;align-items:flex-start;"><div class="metric-title">{html.escape(title)} <span title="{html.escape(what_it_means)}" style="color:#C9A84C;">?</span></div>{badge}</div>
          <div style="margin-top:0.4rem;"><span class="metric-value">{html.escape(ratio_display)}</span><span class="metric-threshold">{threshold_text}</span></div>
          {bar_html}
          <div class="metric-label"><strong style="color:#F5F5F5;">What it means:</strong><br>{html.escape(what_it_means)}</div>
          <div class="metric-label"><strong style="color:#F5F5F5;">Why it matters:</strong><br>{html.escape(why_it_matters)}</div>{note_html}
        </div>''', unsafe_allow_html=True)
    with st.expander("View Calculation"):
        st.markdown(f"**Numerator:** {numerator_label} = {_format_money(numerator)}")
        st.markdown(f"**Denominator:** {denominator_label} = {_format_money(denominator)}")
        if core_interest_business:
            st.markdown("**Result:** Not applicable for this business type")
        else:
            st.markdown(f"**Result:** {NOT_AVAILABLE}" if ratio is None else f"**Result:** {ratio * 100:.1f}% = {_format_money(numerator)} / {_format_money(denominator)}")


def _plain_english_financial_summary(data: dict, screening: dict) -> str:
    company = _company_name(data)
    if _is_core_interest_business(data):
        return (
            f"{company} appears to be a bank, insurer, or similar financial business. "
            "Standard debt, cash, and interest-income ratios can be misleading for this business type, "
            "so the business activity screen should drive the result."
        )
    statuses = _financial_statuses(screening)
    failing = [name for name, status in statuses.items() if status == "fail"]
    close = [name for name, status in statuses.items() if status == "questionable"]
    missing = [name for name, status in statuses.items() if status == "unavailable"]
    if failing:
        return f"{company}'s financials exceed the allowed limit for {', '.join(failing)}. That makes the stock fail the financial screen even if other ratios look acceptable."
    if close:
        return f"{company}'s financials are mostly within the allowable limits. The {', '.join(close)} ratio is close to its threshold, which makes the result questionable."
    if missing:
        return f"{company}'s available financial ratios look acceptable, but some data is missing. Because the available data is incomplete, a scholar should review it before investing."
    return f"{company}'s financials are within the allowable limits. Debt, cash, and interest income levels are below the AAOIFI-style thresholds used by this tool."


def _render_financial_tab(data: dict, screening: dict) -> None:
    _render_metric_card("Debt Ratio", "debt", 0.33, 0.28, "Total Debt", "Market Cap", "Shows how much debt the company carries compared with its market value.", "AAOIFI screening limits excessive debt because it can signal heavy reliance on interest-based financing.")
    _render_metric_card("Interest Income Ratio", "income", 0.05, 0.04, "Interest Income", "Total Revenue", "Shows how much reported income may come from interest compared with total revenue.", "Interest income is monitored because riba is not permissible in Islamic finance.", "Interest income may not be separately reported by all companies.")
    _render_metric_card("Cash & Interest-Bearing Securities Ratio", "cash", 0.33, 0.28, "Total Cash", "Market Cap", "Shows cash and similar holdings compared with the company's market value.", "Large cash or interest-bearing balances can create concern under common halal screening standards.")
    st.markdown(f'<div class="plain-english"><strong>Summary</strong><br>{html.escape(_plain_english_financial_summary(data, screening))}</div>', unsafe_allow_html=True)


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    lowered = (text or "").lower()
    for keyword in keywords:
        if keyword in lowered:
            return keyword
    return None


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
    tab1, tab2, tab3 = st.tabs([
        f"Overview{reset_suffix}",
        f"Financial{reset_suffix}",
        f"Guide{reset_suffix}",
    ])
    with tab1:
        _render_overview_tab(data, screening)
    with tab2:
        _render_financial_tab(data, screening)
    with tab3:
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


def initialize_session_state() -> None:
    defaults = {
        "stock_data": None,
        "screening": None,
        "last_ticker": "",
        "ticker_input": "",
        "tabs_reset_token": 0,
        "has_results": False,
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

def main() -> None:
    st.set_page_config(
        page_title="Halal Stock Checker | iRizq",
        page_icon="static/icon.png",
        layout="centered",
    )

    initialize_session_state()
    inject_head_and_styles()

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

    ticker = st.text_input(
        "Enter Stock Symbol:",
        placeholder="e.g. AAPL",
        label_visibility="visible",
        key="ticker_input",
    ).strip().upper()

    check_clicked = st.button("Check Status", type="primary", use_container_width=True)

    if check_clicked:
        if not ticker:
            st.markdown(
                '<div class="info-msg">Please enter a US stock ticker symbol to continue.</div>',
                unsafe_allow_html=True,
            )
        elif ticker != st.session_state.last_ticker or not st.session_state.has_results:
            run_screening_flow(ticker)
        else:
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


if __name__ == "__main__":
    main()
