from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.forecast import ForecastResponse

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


@router.get("/{district}", response_model=ForecastResponse)
async def get_forecast(
    district: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Return the latest non-stale IMD advisory for a district.
    Reads from the `latest_advisories` view (most recent bulletin_date per district).
    Falls back to stale record if no fresh data exists, flagging is_stale=True.
    """
    # Try fresh record first, then fall back to most recent stale
    result = await session.execute(
        text("""
            SELECT district, state, bulletin_date, rainfall_prob, rainfall_category,
                   min_temp_c, max_temp_c, humidity_pct, wind_speed_kmh, wind_direction,
                   season_outlook, advisory_text, fetched_at, is_stale
            FROM imd_advisories
            WHERE LOWER(district) = LOWER(:district)
            ORDER BY bulletin_date DESC, fetched_at DESC
            LIMIT 1
        """),
        {"district": district},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No forecast found for district '{district}'")
    return ForecastResponse(**dict(row))
