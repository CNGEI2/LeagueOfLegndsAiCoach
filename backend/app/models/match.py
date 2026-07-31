from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MatchRow(Base):
    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    platform: Mapped[str] = mapped_column(String(8), index=True)
    queue_id: Mapped[int] = mapped_column(Integer)
    game_version: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
