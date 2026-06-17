"""
APScheduler setup — runs IMD scraper and staleness check on a daily IST cron.

Standalone entry point: python -m pipeline.scheduler
Also imported by FastAPI lifespan to run scheduler inside the API process.
"""

import asyncio
import logging

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from pipeline.imd_scraper import run_imd_pipeline
from pipeline.staleness import run_staleness_check

log = structlog.get_logger()

# Silence noisy APScheduler logs
logging.getLogger("apscheduler").setLevel(logging.WARNING)


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.imd_scraper_timezone)

    # IMD scraper — 06:00 IST daily
    scheduler.add_job(
        run_imd_pipeline,
        trigger=CronTrigger(
            hour=settings.imd_scraper_cron_hour,
            minute=settings.imd_scraper_cron_minute,
            timezone=settings.imd_scraper_timezone,
        ),
        id="imd_scraper",
        name="IMD GKMS Advisory Scraper",
        replace_existing=True,
        misfire_grace_time=3600,    # run even if delayed up to 1h
    )

    # Staleness check — 06:30 IST daily
    scheduler.add_job(
        run_staleness_check,
        trigger=CronTrigger(
            hour=settings.imd_scraper_cron_hour,
            minute=settings.imd_scraper_cron_minute + 30,
            timezone=settings.imd_scraper_timezone,
        ),
        id="staleness_check",
        name="Data Staleness Marker",
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

    # Run scraper immediately on startup so we don't wait until 6AM
    log.info("running_initial_scrape")
    await run_imd_pipeline()

    try:
        await asyncio.Event().wait()   # block forever
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info("scheduler_stopped")


if __name__ == "__main__":
    asyncio.run(main())
