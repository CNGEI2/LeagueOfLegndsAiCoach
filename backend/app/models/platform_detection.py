from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PlatformDetectionRow(Base):
    __tablename__ = "player_platform_detections"
    __table_args__ = (
        UniqueConstraint(
            "game_name_key",
            "tag_line_key",
            name="uq_player_platform_detections_lookup_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    game_name_key: Mapped[str] = mapped_column(String(128))
    tag_line_key: Mapped[str] = mapped_column(String(64))
    canonical_game_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    canonical_tag_line: Mapped[str | None] = mapped_column(String(64), nullable=True)
    puuid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_status: Mapped[str] = mapped_column(String(16))
    candidate_platforms: Mapped[list[str]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    confirmation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
