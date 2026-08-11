from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MatchTimelineRow(Base):
    __tablename__ = "match_timelines"

    platform: Mapped[str] = mapped_column(String(8), primary_key=True)
    match_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    result_status: Mapped[str] = mapped_column(String(16))
    normalized_snapshot: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    schema_version: Mapped[int] = mapped_column(Integer)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
