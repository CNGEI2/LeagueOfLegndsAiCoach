from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PlayerRow(Base):
    __tablename__ = "players"
    __table_args__ = (UniqueConstraint("platform", "puuid", name="uq_players_platform_puuid"),)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    puuid: Mapped[str] = mapped_column(String(128), index=True)
    platform: Mapped[str] = mapped_column(String(8), index=True)
    game_name: Mapped[str] = mapped_column(String(128))
    tag_line: Mapped[str] = mapped_column(String(64))
    game_name_key: Mapped[str] = mapped_column(String(128), index=True)
    tag_line_key: Mapped[str] = mapped_column(String(64), index=True)
    summoner_level: Mapped[int]
    profile_icon_id: Mapped[int]
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
