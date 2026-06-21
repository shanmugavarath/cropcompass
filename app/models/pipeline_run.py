from datetime import datetime, timezone
from sqlalchemy import Integer, String, Text, DateTime, JSON, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_name:    Mapped[str]           = mapped_column(String(100), nullable=False)
    started_at:       Mapped[datetime]      = mapped_column(
                          DateTime(timezone=True),
                          default=lambda: datetime.now(timezone.utc),
                          nullable=False
                      )
    finished_at:      Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status:           Mapped[str]           = mapped_column(String(20), default="running", nullable=False)
    district_count:   Mapped[int | None]    = mapped_column(Integer)
    new_records:      Mapped[int | None]    = mapped_column(Integer)
    updated_records:  Mapped[int | None]    = mapped_column(Integer)
    failed_districts: Mapped[list | None]   = mapped_column(JSON)
    error_message:    Mapped[str | None]    = mapped_column(Text)
    log_payload:      Mapped[dict | None]   = mapped_column(JSON)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','success','partial','failed')",
            name="chk_pipeline_status"
        ),
    )
