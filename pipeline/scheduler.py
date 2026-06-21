"""
APScheduler setup — all pipeline cron jobs.

Schedule summary:
  06:00 IST daily       → imd_scraper              (GKMS daily advisories)
  06:30 IST daily       → staleness_check           (mark stale records)
  07:00 IST every Mon   → imd_seasonal_scraper      (IMD LRF weekly outlook)
  01:00 IST 1st of month → historical_rainfall_loader (add previous month data)

Standalone: python -m pipeline.scheduler
Also imported by FastAPI lifespan (app/main.py).
"""

import asyncio
import logging

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from pipeline.imd_scraper import run_imd_pipeline
from pipeline.staleness import run_staleness_check
from pipeline.historical_rainfall_loader import run_historical_rainfall_loader
from pipeline.imd_seasonal_scraper import run_imd_seasonal_scraper

log = structlog.get_logger()

logging.getLogger("apscheduler").setLevel(logging.WARNING)


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.imd_scraper_timezone)

    # 06:00 IST daily — IMD GKMS advisory scraper
    scheduler.add_job(
        run_imd_pipeline,
        trigger=CronTrigger(hour=6, minute=0, timezone=settings.imd_scraper_timezone),
        id="imd_scraper",
        name="IMD GKMS Advisory Scraper",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 06:30 IST daily — staleness check
    scheduler.add_job(
        run_staleness_check,
        trigger=CronTrigger(hour=6, minute=30, timezone=settings.imd_scraper_timezone),
        id="staleness_check",
        name="Data Staleness Marker",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 07:00 IST every Monday — IMD LRF seasonal outlook
    scheduler.add_job(
        run_imd_seasonal_scraper,
        trigger=CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=settings.imd_scraper_timezone),
        id="imd_seasonal_scraper",
        name="IMD Seasonal Outlook Scraper",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 01:00 IST 1st of every month — add previous month's historical rainfall
    scheduler.add_job(
        lambda: asyncio.ensure_future(run_historical_rainfall_loader(backfill=False)),
        trigger=CronTrigger(day=1, hour=1, minute=0, timezone=settings.imd_scraper_timezone),
        id="historical_rainfall_monthly",
        name="Historical Rainfall Monthly Refresh",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    return scheduler


async def main():
    """Run scheduler as a standalone process (not inside FastAPI)."""
    scheduler = build_scheduler()
    scheduler.start()

    log.info(
        "scheduler_started",
        jobs=[j.name for j in scheduler.get_jobs()],
        timezone=settings.imd_scraper_timezone,
    )

    # Run initial pipelines on startup
    log.info("running_startup_pipelines")
    await run_imd_pipeline()
    await run_historical_rainfall_loader(backfill=True)
    await run_imd_seasonal_scraper()

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info("scheduler_stopped")


if __name__ == "__main__":
    asyncio.run(main())
