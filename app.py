"""Halal Stock Checker (iRizq.com) - Streamlit UI."""

from __future__ import annotations

import os

import streamlit as st

from data import fetch_stock_data as _fetch_stock_data
from rules import screen_stock


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stock_data_cached(symbol: str):
    """Cached wrapper - reduces Yahoo rate limits on Streamlit Cloud."""
    return _fetch_stock_data(symbol)


PWA_HEAD = """
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Halal Stocks">
<meta name="theme-color" content="#0D1B2A">
<link rel="apple-touch-icon" href="/static/icon.png">
<link rel="manifest" href="/static/manifest.json">
"""

IRIZQ_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  html, body, [class*="css"] {
    font-family: 'Inter', 'Segoe UI', sans-serif;
    background-color: #0D1B2A;
    color: #F5F5F5;
  }
  .main .block-container {
    padding: 1.5rem 1.5rem 3rem 1.5rem;
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
  .company-name {
    color: #C9A84C;
    font-weight: 700;
    font-size: 1.2rem;
  }
  .company-ticker {
    color: #E8C96A;
    font-family: monospace;
    font-size: 1rem;
    font-weight: 600;
  }
  .company-sector {
    color: #8A9BB0;
    font-size: 0.9rem;
    margin-top: 0.2rem;
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
  footer { visibility: hidden; }
  #MainMenu { visibility: hidden; }
  header { visibility: hidden; }
  hr.irizq-divider {
    border: none;
    border-top: 1px solid #2A3F55;
    margin: 1.2rem 0;
  }
</style>
"""

RESULT_ICONS = {
    "pass": "&#9989;",
    "fail": "&#10060;",
    "unknown": "&#9888;&#65039;",
}


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
    return f"""
    <table>
      <thead>
        <tr>
          <th>Check</th>
          <th>Value</th>
          <th>Threshold</th>
          <th>Result</th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
    """


def render_results(data: dict, screening: dict) -> None:
    symbol = data.get("symbol", "N/A")
    company = data.get("company_name") or "N/A"
    sector = data.get("sector") or "N/A"
    result = screening.get("result", "Questionable / Needs Scholar Review")
    reason = screening.get("reason", "")

    st.markdown(f'<div style="margin:1rem 0;">{badge_html(result)}</div>', unsafe_allow_html=True)

    st.markdown(
        f"""
        <div class="company-info">
          <div class="company-name">{company}</div>
          <div class="company-ticker">{symbol}</div>
          <div class="company-sector">{sector}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("## Screening Breakdown")
    st.markdown(breakdown_table_html(screening.get("breakdown", [])), unsafe_allow_html=True)

    st.markdown("## Explanation")
    st.markdown(f'<div class="explanation-card">{reason}</div>', unsafe_allow_html=True)


def render_error(ticker: str) -> None:
    st.markdown(
        f"""
        <div class="error-card">
          Could not retrieve data for <strong>{ticker.upper()}</strong>.
          Please check the symbol and try again.
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Halal Stock Checker | iRizq.com",
        page_icon="static/icon.png",
        layout="centered",
    )

    inject_head_and_styles()

    logo_path = "static/logo.png"
    if os.path.exists(logo_path):
        st.image(logo_path, width=200)

    st.title("Halal Stock Checker")
    st.markdown("### AAOIFI-Based Screening ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ Powered by iRizq.com")
    st.markdown('<hr class="irizq-divider">', unsafe_allow_html=True)

    if "ticker_input" not in st.session_state:
        st.session_state.ticker_input = ""

    ticker = st.text_input(
        "US Stock Ticker",
        value=st.session_state.ticker_input,
        placeholder="e.g. AAPL, MSFT, TSLA",
        label_visibility="collapsed",
    ).strip().upper()

    check_clicked = st.button("Check Stock", type="primary", use_container_width=True)

    if check_clicked:
        if not ticker:
            st.markdown(
                '<div class="info-msg">Please enter a US stock ticker symbol to continue.</div>',
                unsafe_allow_html=True,
            )
        else:
            with st.spinner("Fetching stock data and running AAOIFI screening..."):
                try:
                    stock_data = fetch_stock_data_cached(ticker)
                    if stock_data is None or stock_data.get("error"):
                        render_error(ticker)
                    else:
                        screening = screen_stock(stock_data)
                        render_results(stock_data, screening)
                except Exception:
                    render_error(ticker)

    render_disclaimer()


if __name__ == "__main__":
    main()