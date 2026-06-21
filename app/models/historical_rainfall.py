from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Integer, String, Numeric, Boolean, DateTime, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class IMDHistoricalRainfall(Base):
    __tablename__ = "imd_historical_rainfall"

    id:                 Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    district:           Mapped[str]             = mapped_column(String(100), nullable=False)
    state:              Mapped[str]             = mapped_column(String(100), nullable=False)
    year:               Mapped[int]             = mapped_column(Integer, nullable=False)
    month:              Mapped[int]             = mapped_column(Integer, nullable=False)
    rainfall_mm:        Mapped[Decimal | None]  = mapped_column(Numeric(8, 2))
    normal_rainfall_mm: Mapped[Decimal | None]  = mapped_column(Numeric(8, 2))
    departure_pct:      Mapped[Decimal | None]  = mapped_column(Numeric(6, 2))
    data_source:        Mapped[str]             = mapped_column(String(50), default="open_meteo", nullable=False)
    fetched_at:         Mapped[datetime]        = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_stale:           Mapped[bool]            = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("district", "year", "month", name="uq_historical_district_year_month"),
        CheckConstraint("month BETWEEN 1 AND 12", name="chk_month"),
        CheckConstraint("rainfall_mm IS NULL OR rainfall_mm >= 0", name="chk_rainfall_non_negative"),
    )
