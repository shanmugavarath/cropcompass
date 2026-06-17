from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    Integer, String, Date, Numeric, Boolean, Text, DateTime, UniqueConstraint, CheckConstraint
)
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class IMDAdvisory(Base):
    __tablename__ = "imd_advisories"

    id:                 Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    district:           Mapped[str]             = mapped_column(String(100), nullable=False)
    state:              Mapped[str]             = mapped_column(String(100), nullable=False)
    bulletin_date:      Mapped[date]            = mapped_column(Date, nullable=False)
    rainfall_prob:      Mapped[Decimal | None]  = mapped_column(Numeric(5, 4))
    rainfall_category:  Mapped[str | None]      = mapped_column(String(10))
    min_temp_c:         Mapped[Decimal | None]  = mapped_column(Numeric(5, 2))
    max_temp_c:         Mapped[Decimal | None]  = mapped_column(Numeric(5, 2))
    humidity_pct:       Mapped[Decimal | None]  = mapped_column(Numeric(5, 2))
    wind_speed_kmh:     Mapped[Decimal | None]  = mapped_column(Numeric(6, 2))
    wind_direction:     Mapped[str | None]      = mapped_column(String(20))
    season_outlook:     Mapped[str | None]      = mapped_column(Text)
    advisory_text:      Mapped[str | None]      = mapped_column(Text)
    source_url:         Mapped[str | None]      = mapped_column(String(1000))
    fetched_at:         Mapped[datetime]        = mapped_column(
                            DateTime(timezone=True),
                            default=lambda: datetime.now(timezone.utc),
                            nullable=False
                        )
    is_stale:           Mapped[bool]            = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("district", "bulletin_date", name="uq_advisory_district_date"),
        CheckConstraint("rainfall_prob IS NULL OR (rainfall_prob >= 0 AND rainfall_prob <= 1)", name="chk_rainfall_prob"),
        CheckConstraint("rainfall_category IS NULL OR rainfall_category IN ('low','normal','high')", name="chk_rainfall_category"),
    )

    def __repr__(self) -> str:
        return f"<IMDAdvisory {self.district} {self.bulletin_date} rain={self.rainfall_prob}>"


class IMDDistrictRef(Base):
    __tablename__ = "imd_districts_ref"

    id:         Mapped[int]         = mapped_column(Integer, primary_key=True, autoincrement=True)
    district:   Mapped[str]         = mapped_column(String(100), nullable=False)
    state:      Mapped[str]         = mapped_column(String(100), nullable=False)
    imd_code:   Mapped[str | None]  = mapped_column(String(20))
    latitude:   Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    longitude:  Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    is_active:  Mapped[bool]        = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("district", "state", name="uq_district_state"),
    )
