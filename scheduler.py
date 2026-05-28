"""APScheduler entrypoint for weekly SEC refresh."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from sec_refresh import weekly_sec_refresh

LOGGER = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_weekly_job() -> None:
    summaries = weekly_sec_refresh(
        limit=settings.refresh_default_limit,
        max_filings=settings.refresh_max_filings_per_company,
    )
    LOGGER.info("Weekly SEC refresh completed for %s tracked tickers", len(summaries))


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _run_weekly_job,
        trigger=CronTrigger(
            day_of_week=settings.refresh_cron_day_of_week,
            hour=settings.refresh_cron_hour_utc,
            minute=settings.refresh_cron_minute_utc,
        ),
        id="weekly-sec-refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    LOGGER.info(
        "Scheduler started: weekly-sec-refresh (%s %02d:%02d UTC)",
        settings.refresh_cron_day_of_week,
        settings.refresh_cron_hour_utc,
        settings.refresh_cron_minute_utc,
    )
    _scheduler = scheduler
    return scheduler

