"""
Staleness cron — Task 1.4
Calls mark_stale_records() SQL function and logs the result.
Schedule: APScheduler cron @ 06:30 IST daily (30 min after IMD scraper).
"""

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import settings
from app.models.pipeline_run import PipelineRun

log = structlog.get_logger()


async def run_staleness_check() -> dict:
    engine = create_async_engine(settings.database_url, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as session:
        run = PipelineRun(pipeline_name="staleness_check", status="running")
        session.add(run)
        await session.commit()
        await session.refresh(run)

        try:
            result = await session.execute(text("SELECT mark_stale_records()"))
            payload: dict = result.scalar()

            run.status = "success"
            run.finished_at = datetime.now(timezone.utc)
            run.log_payload = payload
            await session.merge(run)
            await session.commit()

            log.info(
                "staleness_done",
                marked_stale_advisories=payload.get("marked_stale_advisories"),
                marked_stale_farmers=payload.get("marked_stale_farmers"),
            )
            return payload

        except Exception as e:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.error_message = str(e)
            await session.merge(run)
            await session.commit()
            log.error("staleness_error", error=str(e))
            raise

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_staleness_check())
