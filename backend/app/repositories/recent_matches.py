from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.routing import Platform
from app.models.recent_match_cache import RecentMatchCacheRow


class RecentMatchRepository(Protocol):
    async def get(
        self, *, platform: Platform, puuid: str, now: datetime
    ) -> tuple[str, ...] | None: ...

    async def put(
        self,
        *,
        platform: Platform,
        puuid: str,
        match_ids: tuple[str, ...],
        fetched_at: datetime,
        expires_at: datetime,
    ) -> None: ...


class SqlRecentMatchRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, *, platform: Platform, puuid: str, now: datetime) -> tuple[str, ...] | None:
        statement = select(RecentMatchCacheRow.match_ids).where(
            RecentMatchCacheRow.platform == platform.value,
            RecentMatchCacheRow.puuid == puuid,
            RecentMatchCacheRow.expires_at >= now,
        )
        async with self._session_factory() as session:
            match_ids = (await session.execute(statement)).scalar_one_or_none()
        return tuple(match_ids) if match_ids is not None else None

    async def put(
        self,
        *,
        platform: Platform,
        puuid: str,
        match_ids: tuple[str, ...],
        fetched_at: datetime,
        expires_at: datetime,
    ) -> None:
        values = {
            "platform": platform.value,
            "puuid": puuid,
            "match_ids": list(match_ids),
            "fetched_at": fetched_at,
            "expires_at": expires_at,
        }
        statement = insert(RecentMatchCacheRow).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[RecentMatchCacheRow.platform, RecentMatchCacheRow.puuid],
            set_={key: value for key, value in values.items() if key not in {"platform", "puuid"}},
        )
        async with self._session_factory.begin() as session:
            await session.execute(statement)
