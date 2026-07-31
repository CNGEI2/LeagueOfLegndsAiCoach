from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.normalization import lookup_key
from app.core.routing import Platform
from app.models.player import PlayerRow
from app.schemas.domain import PlayerProfile


class PlayerRepository(Protocol):
    async def get_by_riot_id(
        self,
        *,
        platform: Platform,
        game_name_key: str,
        tag_line_key: str,
        fresh_after: datetime,
    ) -> PlayerProfile | None: ...

    async def get_by_puuid(
        self, *, platform: Platform, puuid: str, fresh_after: datetime
    ) -> PlayerProfile | None: ...

    async def upsert(self, profile: PlayerProfile, *, fetched_at: datetime) -> None: ...


class SqlPlayerRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_by_riot_id(
        self,
        *,
        platform: Platform,
        game_name_key: str,
        tag_line_key: str,
        fresh_after: datetime,
    ) -> PlayerProfile | None:
        statement = select(PlayerRow).where(
            PlayerRow.platform == platform.value,
            PlayerRow.game_name_key == game_name_key,
            PlayerRow.tag_line_key == tag_line_key,
            PlayerRow.fetched_at >= fresh_after,
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
        return _to_profile(row) if row is not None else None

    async def get_by_puuid(
        self, *, platform: Platform, puuid: str, fresh_after: datetime
    ) -> PlayerProfile | None:
        statement = select(PlayerRow).where(
            PlayerRow.platform == platform.value,
            PlayerRow.puuid == puuid,
            PlayerRow.fetched_at >= fresh_after,
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
        return _to_profile(row) if row is not None else None

    async def upsert(self, profile: PlayerProfile, *, fetched_at: datetime) -> None:
        values = {
            "puuid": profile.puuid,
            "platform": profile.platform.value,
            "game_name": profile.game_name,
            "tag_line": profile.tag_line,
            "game_name_key": lookup_key(profile.game_name),
            "tag_line_key": lookup_key(profile.tag_line),
            "summoner_level": profile.summoner_level,
            "profile_icon_id": profile.profile_icon_id,
            "fetched_at": fetched_at,
            "updated_at": fetched_at,
        }
        statement = insert(PlayerRow).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[PlayerRow.puuid],
            set_={key: value for key, value in values.items() if key != "puuid"},
        )
        async with self._session_factory.begin() as session:
            await session.execute(statement)


def _to_profile(row: PlayerRow) -> PlayerProfile:
    return PlayerProfile.model_validate(
        {
            "puuid": row.puuid,
            "game_name": row.game_name,
            "tag_line": row.tag_line,
            "platform": row.platform,
            "summoner_level": row.summoner_level,
            "profile_icon_id": row.profile_icon_id,
        }
    )
