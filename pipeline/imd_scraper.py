"""
IMD GKMS Advisory Ingestion Pipeline  —  Task 1.1
Scrapes district-level weather advisories from the IMD agromet portal.

Schedule : APScheduler cron @ 06:00 IST daily
Upsert   : ON CONFLICT (district, bulletin_date) → update, keep latest fetched_at
Logging  : structlog JSON  →  district_count / new_records / failed_districts
"""

import asyncio
import random
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TypedDict

import httpx
import structlog
from bs4 import BeautifulSoup
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings
from app.models.imd_advisory import IMDAdvisory, IMDDistrictRef
from app.models.pipeline_run import PipelineRun

log = structlog.get_logger()

# ── HTTP headers that mimic a real browser ───────────────────────────────────
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://mausam.imd.gov.in/",
}

# ── Typed dict for a parsed advisory row ─────────────────────────────────────
class AdvisoryRow(TypedDict, total=False):
    district:           str
    state:              str
    bulletin_date:      date
    rainfall_prob:      Decimal | None
    rainfall_category:  str | None
    min_temp_c:         Decimal | None
    max_temp_c:         Decimal | None
    humidity_pct:       Decimal | None
    wind_speed_kmh:     Decimal | None
    wind_direction:     str | None
    season_outlook:     str | None
    advisory_text:      str | None
    source_url:         str | None


# ─────────────────────────────────────────────────────────────────────────────
# HTTP + parsing layer
# ─────────────────────────────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def _fetch_page(client: httpx.AsyncClient, url: str, params: dict) -> str:
    resp = await client.get(url, params=params, timeout=settings.imd_scraper_request_timeout)
    resp.raise_for_status()
    return resp.text


def _rainfall_category(prob: Decimal | None) -> str | None:
    if prob is None:
        return None
    if prob < Decimal("0.4"):
        return "low"
    if prob <= Decimal("0.7"):
        return "normal"
    return "high"


def _safe_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        cleaned = value.strip().rstrip("%°").replace(",", ".")
        return Decimal(cleaned)
    except Exception:
        return None


def parse_advisory_html(html: str, district: str, state: str, source_url: str) -> AdvisoryRow | None:
    """
    Parse IMD GKMS advisory HTML page for one district.

    The IMD portal renders a table with rows for each weather parameter.
    Update this function if the portal HTML structure changes — the column
    labels below are based on the known GKMS bulletin table layout.

    HOW TO UPDATE if IMD changes its HTML:
      1. Open the browser DevTools → Network tab
      2. Filter for the district advisory XHR/fetch call
      3. Copy the response HTML and adjust the selectors below
    """
    soup = BeautifulSoup(html, "lxml")

    # ── Strategy 1: look for a <table> with weather rows ─────────────────────
    advisory_text_parts: list[str] = []
    rainfall_prob: Decimal | None = None
    min_temp: Decimal | None = None
    max_temp: Decimal | None = None
    humidity: Decimal | None = None
    wind_speed: Decimal | None = None
    wind_dir: str | None = None
    bulletin_date: date = date.today()

    # Try to extract bulletin date from page
    for tag in soup.find_all(["h2", "h3", "h4", "p", "span", "td"]):
        text_content = tag.get_text(strip=True)
        if "date" in text_content.lower() or "bulletin" in text_content.lower():
            try:
                from dateutil import parser as dateparser
                parsed = dateparser.parse(text_content, fuzzy=True)
                if parsed:
                    bulletin_date = parsed.date()
                    break
            except Exception:
                pass

    # Walk all table rows looking for labelled weather data
    for row in soup.find_all("tr"):
        cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        label = cells[0].lower()
        value = cells[1] if len(cells) > 1 else ""

        if any(k in label for k in ["rainfall", "rain", "precipitation"]):
            # Value might be "74%" or "0.74" or "HIGH"
            if "%" in value:
                rainfall_prob = _safe_decimal(value.replace("%", "").strip())
                if rainfall_prob is not None:
                    rainfall_prob = rainfall_prob / 100
            elif value.upper() in ("HIGH", "NORMAL", "LOW"):
                pass  # handled via category mapping
            else:
                rainfall_prob = _safe_decimal(value)

        elif any(k in label for k in ["min temp", "minimum temp", "min. temp"]):
            min_temp = _safe_decimal(value)

        elif any(k in label for k in ["max temp", "maximum temp", "max. temp"]):
            max_temp = _safe_decimal(value)

        elif "humidity" in label or "r.h." in label:
            humidity = _safe_decimal(value)

        elif "wind speed" in label:
            wind_speed = _safe_decimal(value)

        elif "wind direction" in label:
            wind_dir = value.strip() or None

        # Collect all non-empty cells as advisory text
        row_text = " | ".join(c for c in cells if c)
        if row_text:
            advisory_text_parts.append(row_text)

    # ── Strategy 2: grab any <p> or <div> advisory narrative ─────────────────
    for p in soup.find_all(["p", "div"], class_=lambda c: c and "advisory" in c.lower()):
        advisory_text_parts.append(p.get_text(separator=" ", strip=True))

    if not advisory_text_parts and not rainfall_prob:
        return None  # blank / error page

    advisory_text = "\n".join(advisory_text_parts) if advisory_text_parts else None

    return AdvisoryRow(
        district=district,
        state=state,
        bulletin_date=bulletin_date,
        rainfall_prob=rainfall_prob,
        rainfall_category=_rainfall_category(rainfall_prob),
        min_temp_c=min_temp,
        max_temp_c=max_temp,
        humidity_pct=humidity,
        wind_speed_kmh=wind_speed,
        wind_direction=wind_dir,
        advisory_text=advisory_text,
        source_url=source_url,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Development mock — realistic synthetic data (used when IMD_DEV_MOCK=true)
# ─────────────────────────────────────────────────────────────────────────────

_SEASON_OUTLOOKS = [
    "Normal monsoon expected for the district. Farmers advised to proceed with sowing.",
    "Below-normal rainfall likely. Adopt drought-resistant varieties.",
    "Above-normal rainfall forecast. Ensure proper field drainage before transplanting.",
    "Dry spell expected for next 5 days. Irrigate standing crops if possible.",
    "Heavy rainfall alert. Postpone harvesting operations.",
]

def _mock_advisory(district: str, state: str) -> AdvisoryRow:
    rng = random.Random(f"{district}{date.today()}")
    prob = Decimal(str(round(rng.uniform(0.1, 0.95), 4)))
    min_t = Decimal(str(round(rng.uniform(18, 28), 1)))
    max_t = Decimal(str(round(float(min_t) + rng.uniform(4, 12), 1)))
    humidity = Decimal(str(round(rng.uniform(45, 95), 1)))
    wind_spd = Decimal(str(round(rng.uniform(5, 35), 1)))
    outlook = rng.choice(_SEASON_OUTLOOKS)

    return AdvisoryRow(
        district=district,
        state=state,
        bulletin_date=date.today(),
        rainfall_prob=prob,
        rainfall_category=_rainfall_category(prob),
        min_temp_c=min_t,
        max_temp_c=max_t,
        humidity_pct=humidity,
        wind_speed_kmh=wind_spd,
        wind_direction=rng.choice(["NE", "SW", "SE", "NW", "N", "S"]),
        season_outlook=outlook,
        advisory_text=f"[MOCK] {outlook} Min: {min_t}°C Max: {max_t}°C Humidity: {humidity}%",
        source_url="mock://dev",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Fetch one district — real HTTP or mock
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_district(
    client: httpx.AsyncClient,
    district: str,
    state: str,
) -> AdvisoryRow | None:
    if settings.imd_dev_mock:
        return _mock_advisory(district, state)

    # ── URL + params for the IMD GKMS portal ─────────────────────────────────
    # The portal accepts GET params: state=<name>&dist=<name>
    # Update these if you observe different params in browser DevTools Network tab.
    url = settings.imd_gkms_base_url
    params = {"state": state, "dist": district}

    try:
        html = await _fetch_page(client, url, params)
        row = parse_advisory_html(html, district, state, source_url=str(httpx.URL(url, params=params)))
        if row is None:
            log.warning("parse_empty", district=district, state=state)
        return row
    except httpx.HTTPStatusError as e:
        log.error("http_error", district=district, status=e.response.status_code)
        return None
    except Exception as e:
        log.error("fetch_error", district=district, error=str(e))
        return None


# ─────────────────────────────────────────────────────────────────────────────
# DB upsert
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_advisory(session: AsyncSession, row: AdvisoryRow) -> str:
    """
    Insert or update one advisory row.
    Conflict policy (Task 1.4): on (district, bulletin_date) conflict,
    update all weather fields and reset is_stale=False only if the
    incoming fetched_at is newer than the stored one.
    Returns 'new' or 'updated'.
    """
    stmt = (
        insert(IMDAdvisory)
        .values(
            district=row["district"],
            state=row["state"],
            bulletin_date=row["bulletin_date"],
            rainfall_prob=row.get("rainfall_prob"),
            rainfall_category=row.get("rainfall_category"),
            min_temp_c=row.get("min_temp_c"),
            max_temp_c=row.get("max_temp_c"),
            humidity_pct=row.get("humidity_pct"),
            wind_speed_kmh=row.get("wind_speed_kmh"),
            wind_direction=row.get("wind_direction"),
            season_outlook=row.get("season_outlook"),
            advisory_text=row.get("advisory_text"),
            source_url=row.get("source_url"),
            fetched_at=datetime.now(timezone.utc),
            is_stale=False,
        )
        .on_conflict_do_update(
            constraint="uq_advisory_district_date",
            set_=dict(
                rainfall_prob=      insert(IMDAdvisory).excluded.rainfall_prob,
                rainfall_category=  insert(IMDAdvisory).excluded.rainfall_category,
                min_temp_c=         insert(IMDAdvisory).excluded.min_temp_c,
                max_temp_c=         insert(IMDAdvisory).excluded.max_temp_c,
                humidity_pct=       insert(IMDAdvisory).excluded.humidity_pct,
                wind_speed_kmh=     insert(IMDAdvisory).excluded.wind_speed_kmh,
                wind_direction=     insert(IMDAdvisory).excluded.wind_direction,
                season_outlook=     insert(IMDAdvisory).excluded.season_outlook,
                advisory_text=      insert(IMDAdvisory).excluded.advisory_text,
                source_url=         insert(IMDAdvisory).excluded.source_url,
                fetched_at=         insert(IMDAdvisory).excluded.fetched_at,
                is_stale=           False,
            ),
        )
        .returning(text("xmax"))          # xmax=0 means INSERT, >0 means UPDATE
    )
    result = await session.execute(stmt)
    xmax = result.scalar()
    return "new" if xmax == 0 else "updated"


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline entry point
# ─────────────────────────────────────────────────────────────────────────────

async def run_imd_pipeline() -> dict:
    """
    Fetch advisories for all active districts and upsert into DB.
    Returns a summary dict logged by APScheduler.
    """
    engine = create_async_engine(settings.database_url, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    run_log = structlog.get_logger().bind(pipeline="imd_scraper")
    run_log.info("pipeline_start")

    async with SessionLocal() as session:
        # ── 1. Record pipeline start ─────────────────────────────────────────
        run = PipelineRun(pipeline_name="imd_scraper", status="running")
        session.add(run)
        await session.commit()
        await session.refresh(run)

        # ── 2. Load active districts from reference table ────────────────────
        result = await session.execute(
            select(IMDDistrictRef).where(IMDDistrictRef.is_active == True)
        )
        districts = result.scalars().all()
        run_log.info("districts_loaded", count=len(districts))

        # ── 3. Scrape concurrently (bounded by semaphore) ────────────────────
        sem = asyncio.Semaphore(settings.imd_scraper_concurrency)
        new_count = updated_count = 0
        failed: list[str] = []

        async def _process(client: httpx.AsyncClient, ref: IMDDistrictRef):
            nonlocal new_count, updated_count
            async with sem:
                row = await fetch_district(client, ref.district, ref.state)
            if row is None:
                failed.append(ref.district)
                return
            async with SessionLocal() as s:
                try:
                    action = await upsert_advisory(s, row)
                    await s.commit()
                    if action == "new":
                        new_count += 1
                    else:
                        updated_count += 1
                    run_log.info(
                        "upserted",
                        district=ref.district,
                        action=action,
                        rainfall_prob=str(row.get("rainfall_prob")),
                        rainfall_category=row.get("rainfall_category"),
                    )
                except Exception as e:
                    await s.rollback()
                    failed.append(ref.district)
                    run_log.error("upsert_error", district=ref.district, error=str(e))

        async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True) as client:
            await asyncio.gather(*[_process(client, ref) for ref in districts])

        # ── 4. Finalise pipeline run record ──────────────────────────────────
        status = "success" if not failed else ("partial" if new_count + updated_count > 0 else "failed")
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        run.district_count = len(districts)
        run.new_records = new_count
        run.updated_records = updated_count
        run.failed_districts = failed or None
        run.log_payload = {
            "district_count": len(districts),
            "new_records": new_count,
            "updated_records": updated_count,
            "failed_districts": failed,
        }
        await session.merge(run)
        await session.commit()

    summary = {
        "district_count": len(districts),
        "new_records": new_count,
        "updated_records": updated_count,
        "failed_districts": failed,
        "status": status,
    }
    run_log.info("pipeline_done", **summary)
    await engine.dispose()
    return summary


# ── Run directly: python -m pipeline.imd_scraper ─────────────────────────────
if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    asyncio.run(run_imd_pipeline())
