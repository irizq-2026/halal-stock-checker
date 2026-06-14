"""CLI utility to refresh Ethical Insights flags from live sources."""

from __future__ import annotations

import argparse
from typing import Iterable

from db import session_scope
from logging_setup import configure_logging
from sec_refresh import latest_cached_screen_row
from services.ethical_insights import resolve_ethical_insights

DEFAULT_TICKERS: tuple[str, ...] = (
    "AAPL",
    "CRCL",
    "MSFT",
    "PLTR",
    "QS",
    "SPCX",
    "TSLA",
    "JPM",
    "XOM",
    "AMZN",
)


def _normalize_tickers(raw: str) -> list[str]:
    if not raw:
        return list(DEFAULT_TICKERS)
    out: list[str] = []
    for part in raw.split(","):
        ticker = part.strip().upper()
        if ticker and ticker not in out:
            out.append(ticker)
    return out


def refresh_ethical_flags(tickers: Iterable[str]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    with session_scope() as session:
        for ticker in tickers:
            row = latest_cached_screen_row(session, ticker)
            if row is None:
                summaries.append(
                    {
                        "ticker": ticker,
                        "status": "skipped",
                        "message": "No cached SEC row found",
                    }
                )
                continue

            company, _, normalized, screen_result = row
            insights = resolve_ethical_insights(company.ticker, company.company_name)

            normalized_meta = dict(normalized.source_metadata_json or {})
            normalized_meta["ethical_insights"] = insights
            normalized.source_metadata_json = normalized_meta

            result_meta = dict(screen_result.mapped_tags_json or {})
            result_meta["ethical_insights"] = insights
            screen_result.mapped_tags_json = result_meta

            summaries.append(
                {
                    "ticker": company.ticker,
                    "status": "updated",
                    "official_bds": insights.get("official_bds", False),
                    "afsc": insights.get("afsc", False),
                    "un_ohchr": insights.get("un_ohchr", False),
                    "who_profits": insights.get("who_profits", False),
                }
            )
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Ethical Insights flags")
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated ticker list. Defaults to current local Streamlit watchlist universe.",
    )
    args = parser.parse_args()

    configure_logging()
    tickers = _normalize_tickers(args.tickers)
    summaries = refresh_ethical_flags(tickers)
    print(f"Processed {len(summaries)} ticker(s)")
    for summary in summaries:
        print(summary)


if __name__ == "__main__":
    main()
