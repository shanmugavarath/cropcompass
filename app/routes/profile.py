import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.farmer import Farmer
from app.schemas.farmer import FarmerCreate, FarmerResponse, FarmerUpdate

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.post("", response_model=FarmerResponse, status_code=status.HTTP_201_CREATED)
async def create_profile(
    body: FarmerCreate,
    session: AsyncSession = Depends(get_session),
):
    farmer = Farmer(**body.model_dump())
    session.add(farmer)
    await session.commit()
    await session.refresh(farmer)
    return farmer


@router.get("/{farmer_id}", response_model=FarmerResponse)
async def get_profile(
    farmer_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Farmer).where(Farmer.farmer_id == farmer_id))
    farmer = result.scalar_one_or_none()
    if farmer is None:
        raise HTTPException(status_code=404, detail="Farmer not found")
    return farmer


@router.patch("/{farmer_id}", response_model=FarmerResponse)
async def update_profile(
    farmer_id: uuid.UUID,
    body: FarmerUpdate,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(Farmer).where(Farmer.farmer_id == farmer_id))
    farmer = result.scalar_one_or_none()
    if farmer is None:
        raise HTTPException(status_code=404, detail="Farmer not found")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(farmer, field, value)
    farmer.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(farmer)
    return farmer
