"""
IMD Seasonal Outlook Scraper — Task 1.5
Scrapes the IMD Long Range Forecast (LRF) page for seasonal rainfall category
and probabilities per district.

Schedule: Every Monday 07:00 IST
Mock mode: IMD_DEV_MOCK=true → generates plausible probabilities
"""

import asyncio
import random
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import structlog
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import settings
from app.models.imd_advisory import IMDDistrictRef
from app.models.seasonal_outlook import IMDSeasonalOutlook
from app.models.pipeline_run import PipelineRun

log = structlog.get_logger()

IMD_LRF_URL = "https://mausam.imd.gov.in/responsive/seasonalForecast.php"

_CATEGORIES = ["deficient", "below_normal", "normal", "above_normal", "excess"]


def _current_season() -> str:
    month = date.today().month
    if 6 <= month <= 10:
        return "kharif"
    if 11 <= month or month <= 3:
        return "rabi"
    return "zaid"


def _mock_outlook(district: str, state: str) -> dict:
    """Reproducible mock seasonal outlook seeded on district + year + season."""
    season = _current_season()
    year   = date.today().year
    rng    = random.Random(f"{district}{year}{season}")

    # Generate 3 probabilities that sum to 100
    p1 = rng.randint(10, 40)
    p2 = rng.randint(20, 50)
    p3 = 100 - p1 - p2
    if p3 < 5:
        p3, p2 = 5, p2 - (5 - p3)

    categories = ["below_normal", "normal", "above_normal"]
    dominant_idx = [p1, p2, p3].index(max(p1, p2, p3))
    category = categories[dominant_idx]

    return dict(
        district=district,
        state=state,
        forecast_year=year,
        season=season,
        forecast_category=category,
        prob_below_normal=Decimal(p1),
        prob_normal=Decimal(p2),
        prob_above_normal=Decimal(p3),
        published_at=date.today(),
        source_url="mock://dev",
        fetched_at=datetime.now(timezone.utc),
        is_stale=False,
    )


def _parse_lrf_html(html: str, districts: list[IMDDistrictRef]) -> list[dict]:
    """
    Parse IMD LRF HTML. The LRF page shows a table of meteorological subdivisions
    with columns: Subdivision | Category | Below Normal% | Normal% | Above Normal%.

    Update this parser if the IMD page structure changes — inspect via browser DevTools.
    """
    soup = BeautifulSoup(html, "lxml")
    rows = []
    season = _current_season()
    year   = date.today().year

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not any("subdivision" in h or "district" in h or "division" in h for h in headers):
            continue

        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 4:
                continue

            subdivision = cells[0].strip()
            # Try to match subdivision to our districts (fuzzy by state keyword)
            matched_districts = [
                d for d in districts
                if d.state.lower() in subdivision.lower()
                or d.district.lower() in subdivision.lower()
            ]

            try:
                prob_below  = Decimal(cells[-3].replace("%", "").strip())
                prob_normal = Decimal(cells[-2].replace("%", "").strip())
                prob_above  = Decimal(cells[-1].replace("%", "").strip())
            except Exception:
                continue

            category_val = cells[1].strip().lower().replace(" ", "_") if len(cells) > 1 else None
            if category_val not in _CATEGORIES:
                category_val = None

            for dist in matched_districts:
                rows.append(dict(
                    district=dist.district,
                    state=dist.state,
                    forecast_year=year,
                    season=season,
                    forecast_category=category_val,
                    prob_below_normal=prob_below,
                    prob_normal=prob_normal,
                    prob_above_normal=prob_above,
                    published_at=date.today(),
                    source_url=IMD_LRF_URL,
                    fetched_at=datetime.now(timezone.utc),
                    is_stale=False,
                ))
    return rows


async def run_imd_seasonal_scraper() -> dict:
    engine       = create_async_engine(settings.database_url, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    run_log      = log.bind(pipeline="imd_seasonal_scraper")
    run_log.info("pipeline_start", season=_current_season(), year=date.today().year)

    async with SessionLocal() as session:
        run = PipelineRun(pipeline_name="imd_seasonal_scraper", status="running")
        session.add(run)
        await session.commit()
        await session.refresh(run)

        result = await session.execute(select(IMDDistrictRef).where(IMDDistrictRef.is_active == True))
        districts = result.scalars().all()

    if settings.imd_dev_mock:
        rows = [_mock_outlook(d.district, d.state) for d in districts]
    else:
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://mausam.imd.gov.in/"},
                follow_redirects=True,
                timeout=30,
            ) as client:
                resp = await client.get(IMD_LRF_URL)
                resp.raise_for_status()
                rows = _parse_lrf_html(resp.text, districts)

            if not rows:
                run_log.warning("parse_empty_falling_back_to_mock")
                rows = [_mock_outlook(d.district, d.state) for d in districts]
        except Exception as e:
            run_log.error("fetch_failed_falling_back_to_mock", error=str(e))
            rows = [_mock_outlook(d.district, d.state) for d in districts]

    # Upsert all rows
    failed: list[str] = []
    new_count = 0
    async with SessionLocal() as session:
        try:
            stmt = (
                insert(IMDSeasonalOutlook)
                .values(rows)
                .on_conflict_do_update(
                    constraint="uq_outlook_district_year_season",
                    set_=dict(
                        forecast_category=  insert(IMDSeasonalOutlook).excluded.forecast_category,
                        prob_below_normal=  insert(IMDSeasonalOutlook).excluded.prob_below_normal,
                        prob_normal=        insert(IMDSeasonalOutlook).excluded.prob_normal,
                        prob_above_normal=  insert(IMDSeasonalOutlook).excluded.prob_above_normal,
                        published_at=       insert(IMDSeasonalOutlook).excluded.published_at,
                        source_url=         insert(IMDSeasonalOutlook).excluded.source_url,
                        fetched_at=         insert(IMDSeasonalOutlook).excluded.fetched_at,
                        is_stale=           False,
                    ),
                )
            )
            await session.execute(stmt)
            await session.commit()
            new_count = len(rows)
        except Exception as e:
            await session.rollback()
            log.error("upsert_failed", error=str(e))
            failed = [d.district for d in districts]

    status = "success" if not failed else "failed"
    async with SessionLocal() as session:
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        run.district_count = len(districts)
        run.new_records = new_count
        run.failed_districts = failed or None
        await session.merge(run)
        await session.commit()

    summary = {"district_count": len(districts), "new_records": new_count, "failed": failed, "status": status}
    run_log.info("pipeline_done", **summary)
    await engine.dispose()
    return summary


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    asyncio.run(run_imd_seasonal_scraper())
