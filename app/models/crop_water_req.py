from sqlalchemy import Integer, String, Boolean, Text, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class CropWaterRequirement(Base):
    __tablename__ = "crop_water_requirements"

    id:                    Mapped[int]        = mapped_column(Integer, primary_key=True, autoincrement=True)
    crop_name:             Mapped[str]        = mapped_column(String(100), nullable=False, unique=True)
    min_rainfall_mm:       Mapped[int]        = mapped_column(Integer, nullable=False)
    optimal_rainfall_mm:   Mapped[int]        = mapped_column(Integer, nullable=False)
    max_rainfall_mm:       Mapped[int]        = mapped_column(Integer, nullable=False)
    growing_duration_days: Mapped[int]        = mapped_column(Integer, nullable=False)
    kharif_suitable:       Mapped[bool]       = mapped_column(Boolean, default=False, nullable=False)
    rabi_suitable:         Mapped[bool]       = mapped_column(Boolean, default=False, nullable=False)
    zaid_suitable:         Mapped[bool]       = mapped_column(Boolean, default=False, nullable=False)
    water_sensitivity:     Mapped[str]        = mapped_column(String(10), default="medium", nullable=False)
    notes:                 Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("water_sensitivity IN ('high','medium','low')", name="chk_sensitivity"),
        CheckConstraint("min_rainfall_mm <= optimal_rainfall_mm AND optimal_rainfall_mm <= max_rainfall_mm", name="chk_rainfall_order"),
    )
