import hashlib
import json
from datetime import datetime
from typing import Protocol, cast

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ApiError
from app.core.routing import Platform
from app.models.match import MatchRow
from app.schemas.domain import MatchSnapshot

SCHEMA_VERSION = 1


class MatchCacheConflict(Exception):
    """A completed match ID was fetched with incompatible normalized content."""


class MatchRepository(Protocol):
    async def get(
        self,
        *,
        platform: Platform,
        match_id: str,
        fresh_after: datetime,
    ) -> MatchSnapshot | None: ...

    async def get_for_replay_binding(
        self,
        *,
        platform: Platform,
        match_id: str,
    ) -> MatchSnapshot | None: ...

    async def put(self, snapshot: MatchSnapshot, *, fetched_at: datetime) -> None: ...

    async def delete_expired(self, *, before: datetime) -> int: ...


class SqlMatchRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(
        self,
        *,
        platform: Platform,
        match_id: str,
        fresh_after: datetime,
    ) -> MatchSnapshot | None:
        statement = select(MatchRow).where(
            MatchRow.platform == platform.value,
            MatchRow.match_id == match_id,
            MatchRow.fetched_at >= fresh_after,
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
        return (
            None if row is None else _snapshot_from_row(row, platform=platform, match_id=match_id)
        )

    async def get_for_replay_binding(
        self,
        *,
        platform: Platform,
        match_id: str,
    ) -> MatchSnapshot | None:
        statement = select(MatchRow).where(
            MatchRow.platform == platform.value,
            MatchRow.match_id == match_id,
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
        return (
            None if row is None else _snapshot_from_row(row, platform=platform, match_id=match_id)
        )

    async def put(self, snapshot: MatchSnapshot, *, fetched_at: datetime) -> None:
        normalized_snapshot = snapshot.model_dump(mode="json")
        snapshot_hash = _snapshot_hash(normalized_snapshot)
        values = {
            "match_id": snapshot.match_id,
            "platform": snapshot.platform.value,
            "queue_id": snapshot.queue_id,
            "game_version": snapshot.game_version,
            "started_at": snapshot.started_at,
            "duration_seconds": snapshot.duration_seconds,
            "snapshot": normalized_snapshot,
            "schema_version": SCHEMA_VERSION,
            "snapshot_hash": snapshot_hash,
            "fetched_at": fetched_at,
        }
        statement = insert(MatchRow).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[MatchRow.match_id],
            set_={"fetched_at": fetched_at},
            where=(
                (MatchRow.schema_version == SCHEMA_VERSION)
                & (MatchRow.snapshot_hash == snapshot_hash)
            ),
        )
        async with self._session_factory.begin() as session:
            result = await session.execute(statement)
            if _rowcount(result) != 0:
                return
            raise MatchCacheConflict("match cache content differs from the completed snapshot")

    async def delete_expired(self, *, before: datetime) -> int:
        statement = delete(MatchRow).where(MatchRow.fetched_at < before)
        async with self._session_factory.begin() as session:
            result = await session.execute(statement)
        return _rowcount(result)


def _snapshot_hash(snapshot: dict[str, object]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _snapshot_from_row(
    row: MatchRow,
    *,
    platform: Platform,
    match_id: str,
) -> MatchSnapshot:
    if (
        row.platform != platform.value
        or row.match_id != match_id
        or row.schema_version != SCHEMA_VERSION
        or _snapshot_hash(row.snapshot) != row.snapshot_hash
    ):
        raise _invalid_cached_match()
    try:
        snapshot = MatchSnapshot.model_validate(row.snapshot)
    except ValidationError as error:
        raise _invalid_cached_match() from error
    if (
        snapshot.platform != platform
        or snapshot.match_id != match_id
        or snapshot.queue_id != row.queue_id
        or snapshot.game_version != row.game_version
        or snapshot.started_at != row.started_at
        or snapshot.duration_seconds != row.duration_seconds
    ):
        raise _invalid_cached_match()
    return snapshot


def _invalid_cached_match() -> ApiError:
    return ApiError(
        status_code=502,
        code="RIOT_INVALID_RESPONSE",
        message="Riot returned an invalid response.",
        retryable=False,
    )


def _rowcount(result: object) -> int:
    return cast(CursorResult[object], result).rowcount
