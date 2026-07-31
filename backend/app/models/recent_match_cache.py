from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RecentMatchCacheRow(Base):
    __tablename__ = "recent_match_caches"

    platform: Mapped[str] = mapped_column(String(8), primary_key=True)
    puuid: Mapped[str] = mapped_column(String(128), primary_key=True)
    match_ids: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
