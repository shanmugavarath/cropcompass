from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Integer, String, Numeric, Boolean, Date, DateTime, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class IMDSeasonalOutlook(Base):
    __tablename__ = "imd_seasonal_outlook"

    id:                 Mapped[int]             = mapped_column(Integer, primary_key=True, autoincrement=True)
    district:           Mapped[str]             = mapped_column(String(100), nullable=False)
    state:              Mapped[str]             = mapped_column(String(100), nullable=False)
    forecast_year:      Mapped[int]             = mapped_column(Integer, nullable=False)
    season:             Mapped[str]             = mapped_column(String(20), nullable=False)
    forecast_category:  Mapped[str | None]      = mapped_column(String(20))
    prob_below_normal:  Mapped[Decimal | None]  = mapped_column(Numeric(5, 2))
    prob_normal:        Mapped[Decimal | None]  = mapped_column(Numeric(5, 2))
    prob_above_normal:  Mapped[Decimal | None]  = mapped_column(Numeric(5, 2))
    published_at:       Mapped[date | None]     = mapped_column(Date)
    source_url:         Mapped[str | None]      = mapped_column(String(1000))
    fetched_at:         Mapped[datetime]        = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_stale:           Mapped[bool]            = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("district", "forecast_year", "season", name="uq_outlook_district_year_season"),
        CheckConstraint("season IN ('kharif','rabi','annual')", name="chk_season"),
        CheckConstraint(
            "forecast_category IS NULL OR forecast_category IN ('deficient','below_normal','normal','above_normal','excess')",
            name="chk_category"
        ),
    )
