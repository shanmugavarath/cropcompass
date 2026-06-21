"""
Historical Rainfall Loader — Task 1.5
Fetches monthly precipitation from the Open-Meteo archive API (free, no auth).

Schedule:
  - On startup (once): backfill Jan 2015 → last complete month
  - 01:00 IST 1st of every month: add previous month's data
"""

import asyncio
import random
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings
from app.models.imd_advisory import IMDDistrictRef
from app.models.historical_rainfall import IMDHistoricalRainfall
from app.models.pipeline_run import PipelineRun

log = structlog.get_logger()

OPEN_METEO_URL  = "https://archive-api.open-meteo.com/v1/archive"
BACKFILL_START  = date(2015, 1, 1)
REQUEST_DELAY_S = 1.2   # seconds between Open-Meteo requests (free tier: ~60 req/min)

# Typical monthly rainfall normals (mm) for Indian climate zones — used for mock data
_MOCK_MONTHLY_BASE = [8, 10, 15, 25, 40, 120, 180, 160, 100, 80, 30, 12]


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=15),
    reraise=True,
)
async def _fetch_open_meteo(client: httpx.AsyncClient, lat: float, lon: float, start: date, end: date) -> dict:
    resp = await client.get(OPEN_METEO_URL, params={
        "latitude":    lat,
        "longitude":   lon,
        "start_date":  start.isoformat(),
        "end_date":    end.isoformat(),
        "daily":       "precipitation_sum",
        "timezone":    "Asia/Kolkata",
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _daily_to_monthly(dates: list[str], values: list[float | None]) -> dict[tuple[int, int], Decimal]:
    """Aggregate daily precipitation → {(year, month): total_mm}."""
    monthly: dict[tuple[int, int], Decimal] = {}
    for d_str, val in zip(dates, values):
        d = date.fromisoformat(d_str)
        key = (d.year, d.month)
        monthly[key] = monthly.get(key, Decimal(0)) + Decimal(str(val or 0))
    return {k: v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for k, v in monthly.items()}


def _compute_normals(all_monthly: dict[tuple[int, int], Decimal]) -> dict[int, Decimal]:
    """Return {month: avg_mm} across all years — the 'normal' for each calendar month."""
    by_month: dict[int, list[Decimal]] = {m: [] for m in range(1, 13)}
    for (_, month), val in all_monthly.items():
        by_month[month].append(val)
    return {
        m: (Decimal(str(sum(vals) / len(vals))).quantize(Decimal("0.01")) if vals else Decimal(0))
        for m, vals in by_month.items()
    }


async def _upsert_monthly(session: AsyncSession, district: str, state: str,
                           monthly: dict[tuple[int, int], Decimal],
                           normals: dict[int, Decimal]) -> tuple[int, int]:
    new_count = updated_count = 0
    rows = []
    for (year, month), rainfall in monthly.items():
        normal = normals.get(month, Decimal(0))
        departure = (
            ((rainfall - normal) / normal * 100).quantize(Decimal("0.01"))
            if normal > 0 else Decimal(0)
        )
        rows.append(dict(
            district=district,
            state=state,
            year=year,
            month=month,
            rainfall_mm=rainfall,
            normal_rainfall_mm=normal,
            departure_pct=departure,
            data_source="open_meteo",
            fetched_at=datetime.now(timezone.utc),
            is_stale=False,
        ))

    if not rows:
        return 0, 0

    stmt = (
        insert(IMDHistoricalRainfall)
        .values(rows)
        .on_conflict_do_update(
            constraint="uq_historical_district_year_month",
            set_=dict(
                rainfall_mm=        insert(IMDHistoricalRainfall).excluded.rainfall_mm,
                normal_rainfall_mm= insert(IMDHistoricalRainfall).excluded.normal_rainfall_mm,
                departure_pct=      insert(IMDHistoricalRainfall).excluded.departure_pct,
                fetched_at=         insert(IMDHistoricalRainfall).excluded.fetched_at,
                is_stale=           False,
            ),
        )
        .returning(IMDHistoricalRainfall.id)
    )
    result = await session.execute(stmt)
    # All rows returned — approximate new vs updated via count
    total = len(result.fetchall())
    new_count = total      # simplified; xmax per-row tracking omitted for bulk insert
    return new_count, 0


def _mock_monthly(district: str, start: date, end: date) -> dict[tuple[int, int], Decimal]:
    """Generate reproducible synthetic monthly rainfall for dev/testing."""
    rng = random.Random(district)
    # Scale factor: coastal districts get more rain, arid get less
    scale = rng.uniform(0.5, 2.0)
    monthly: dict[tuple[int, int], Decimal] = {}
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        base = _MOCK_MONTHLY_BASE[m - 1] * scale
        noise = rng.uniform(0.6, 1.4)
        monthly[(y, m)] = Decimal(str(round(base * noise, 2)))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return monthly


async def load_district(
    client: httpx.AsyncClient,
    session_factory,
    ref: IMDDistrictRef,
    start: date,
    end: date,
    mock: bool = False,
) -> bool:
    try:
        if mock:
            monthly = _mock_monthly(ref.district, start, end)
        else:
            if ref.latitude is None or ref.longitude is None:
                log.warning("no_coordinates", district=ref.district)
                return False
            await asyncio.sleep(REQUEST_DELAY_S)   # respect Open-Meteo free-tier rate limit
            data = await _fetch_open_meteo(client, float(ref.latitude), float(ref.longitude), start, end)
            monthly = _daily_to_monthly(data["daily"]["time"], data["daily"]["precipitation_sum"])

        normals = _compute_normals(monthly)
        async with session_factory() as session:
            await _upsert_monthly(session, ref.district, ref.state, monthly, normals)
            await session.commit()

        log.info("district_loaded", district=ref.district, months=len(monthly))
        return True

    except Exception as e:
        log.error("district_load_failed", district=ref.district, error=str(e))
        return False


async def run_historical_rainfall_loader(backfill: bool = False) -> dict:
    """
    backfill=True  → load Jan 2015 → last complete month (startup call)
    backfill=False → load previous calendar month only (monthly cron call)
    """
    engine = create_async_engine(settings.database_url, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    run_log = log.bind(pipeline="historical_rainfall_loader")

    today = date.today()
    if backfill:
        start = BACKFILL_START
    else:
        # Previous month
        first_of_this_month = today.replace(day=1)
        prev_month_last = first_of_this_month.replace(day=1) - __import__("datetime").timedelta(days=1)
        start = prev_month_last.replace(day=1)

    # End = last day of previous month
    first_this = today.replace(day=1)
    end = (first_this - __import__("datetime").timedelta(days=1))

    if start > end:
        run_log.info("no_data_needed", start=start.isoformat(), end=end.isoformat())
        await engine.dispose()
        return {"status": "skipped", "reason": "start > end"}

    run_log.info("pipeline_start", start=start.isoformat(), end=end.isoformat(), backfill=backfill)

    async with SessionLocal() as session:
        run = PipelineRun(pipeline_name="historical_rainfall_loader", status="running")
        session.add(run)
        await session.commit()
        await session.refresh(run)

        result_districts = await session.execute(
            select(IMDDistrictRef).where(IMDDistrictRef.is_active == True)
        )
        districts = result_districts.scalars().all()

    sem = asyncio.Semaphore(settings.imd_scraper_concurrency)
    failed: list[str] = []
    success_count = 0

    async def _bounded(client, ref):
        nonlocal success_count
        async with sem:
            ok = await load_district(client, SessionLocal, ref, start, end, mock=settings.imd_dev_mock)
        if ok:
            success_count += 1
        else:
            failed.append(ref.district)

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[_bounded(client, ref) for ref in districts])

    status = "success" if not failed else ("partial" if success_count > 0 else "failed")
    async with SessionLocal() as session:
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        run.district_count = len(districts)
        run.new_records = success_count
        run.failed_districts = failed or None
        await session.merge(run)
        await session.commit()

    summary = {"district_count": len(districts), "loaded": success_count, "failed": failed, "status": status}
    run_log.info("pipeline_done", **summary)
    await engine.dispose()
    return summary


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    asyncio.run(run_historical_rainfall_loader(backfill=True))
