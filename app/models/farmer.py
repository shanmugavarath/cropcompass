import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class Farmer(Base):
    __tablename__ = "farmers"

    farmer_id:    Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    name:         Mapped[str | None]   = mapped_column(String(200))
    phone:        Mapped[str | None]   = mapped_column(String(20))
    district:     Mapped[str]          = mapped_column(String(100), nullable=False)
    state:        Mapped[str]          = mapped_column(String(100), nullable=False)
    soil_type:    Mapped[str | None]   = mapped_column(String(50))
    crop_variety: Mapped[str | None]   = mapped_column(String(100))
    growth_stage: Mapped[str | None]   = mapped_column(String(50))
    lang_pref:    Mapped[str]          = mapped_column(String(20), nullable=False, default="eng_Latn")
    created_at:   Mapped[datetime]     = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at:   Mapped[datetime]     = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    is_stale:     Mapped[bool]         = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        CheckConstraint("lang_pref IN ('hin_Deva','tam_Taml','tel_Telu','mar_Deva','pan_Guru','eng_Latn','ben_Beng','kan_Knda','mal_Mlym')", name="chk_lang_pref"),
        CheckConstraint("soil_type IS NULL OR soil_type IN ('loamy','clay','sandy','black','red','alluvial','laterite')", name="chk_soil_type"),
        CheckConstraint("crop_variety IS NULL OR crop_variety IN ('rice','wheat','maize','cotton','soybean','sugarcane','pulses','vegetables')", name="chk_crop_variety"),
        CheckConstraint("growth_stage IS NULL OR growth_stage IN ('sowing','germination','vegetative','flowering','fruiting','harvesting')", name="chk_growth_stage"),
    )

    def __repr__(self) -> str:
        return f"<Farmer {self.farmer_id} {self.district} {self.lang_pref}>"
