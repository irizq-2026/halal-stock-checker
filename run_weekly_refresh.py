"""CLI utility for manual/cron SEC refresh runs."""

from __future__ import annotations

import argparse

from config import settings
from logging_setup import configure_logging
from sec_refresh import refresh_single_ticker, weekly_sec_refresh


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SEC cache refresh")
    parser.add_argument("--ticker", help="Refresh only one ticker", default="")
    parser.add_argument("--force", action="store_true", help="Recompute even if filing already processed")
    parser.add_argument("--limit", type=int, default=settings.refresh_default_limit)
    args = parser.parse_args()

    configure_logging()
    if args.ticker:
        summary = refresh_single_ticker(
            args.ticker,
            force=args.force,
            max_filings=settings.refresh_max_filings_per_company,
        )
        print(summary)
        return

    summaries = weekly_sec_refresh(
        limit=max(args.limit, 0),
        force=args.force,
        max_filings=settings.refresh_max_filings_per_company,
    )
    print(f"Processed {len(summaries)} companies")
    for summary in summaries:
        print(summary)


if __name__ == "__main__":
    main()
