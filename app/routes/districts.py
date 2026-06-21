from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter(prefix="/api/districts", tags=["districts"])


@router.get("")
async def list_districts(
    session: AsyncSession = Depends(get_session),
):
    """
    Return the master list of valid district names for onboarding dropdowns.
    Sourced from the distinct districts present in IMD advisories.
    """
    result = await session.execute(
        text("""
            SELECT DISTINCT district
            FROM imd_advisories
            ORDER BY district
        """)
    )
    districts = [row[0] for row in result.all()]
    return {"districts": districts}
