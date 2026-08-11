from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.routing import Platform
from app.models.timeline import MatchTimelineRow

TimelineCacheStatus = Literal["available", "not_found"]


@dataclass(frozen=True)
class TimelineCacheRecord:
    platform: Platform
    match_id: str
    result_status: TimelineCacheStatus
    normalized_snapshot: dict[str, object] | None
    schema_version: int
    snapshot_hash: str | None
    fetched_at: datetime
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _validate_timezone(self.fetched_at, "fetched_at")
        _validate_timezone(self.expires_at, "expires_at")
        _validate_timezone(self.created_at, "created_at")
        _validate_timezone(self.updated_at, "updated_at")
        if not isinstance(self.platform, Platform):
            raise ValueError(f"invalid platform: {self.platform!r}")
        if self.result_status not in {"available", "not_found"}:
            raise ValueError(f"unsupported timeline cache status: {self.result_status!r}")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        if self.result_status == "available":
            if self.normalized_snapshot is None or self.snapshot_hash is None:
                raise ValueError("available timeline cache requires snapshot and hash")
            return
        if self.normalized_snapshot is not None or self.snapshot_hash is not None:
            raise ValueError("not_found timeline cache must not set snapshot or hash")


class TimelineRepository(Protocol):
    async def get_fresh(
        self, *, platform: Platform, match_id: str, now: datetime
    ) -> TimelineCacheRecord | None: ...

    async def upsert(self, record: TimelineCacheRecord) -> TimelineCacheRecord: ...


class SqlTimelineRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_fresh(
        self, *, platform: Platform, match_id: str, now: datetime
    ) -> TimelineCacheRecord | None:
        _validate_timezone(now, "now")
        statement = select(MatchTimelineRow).where(
            MatchTimelineRow.platform == platform.value,
            MatchTimelineRow.match_id == match_id,
            MatchTimelineRow.expires_at > now,
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
        return _to_record(row) if row is not None else None

    async def upsert(self, record: TimelineCacheRecord) -> TimelineCacheRecord:
        values = {
            "platform": record.platform.value,
            "match_id": record.match_id,
            "result_status": record.result_status,
            "normalized_snapshot": record.normalized_snapshot,
            "schema_version": record.schema_version,
            "snapshot_hash": record.snapshot_hash,
            "fetched_at": record.fetched_at,
            "expires_at": record.expires_at,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
        insert_statement = insert(MatchTimelineRow).values(**values)
        upsert_statement = insert_statement.on_conflict_do_update(
            index_elements=[MatchTimelineRow.platform, MatchTimelineRow.match_id],
            set_={
                "result_status": insert_statement.excluded.result_status,
                "normalized_snapshot": insert_statement.excluded.normalized_snapshot,
                "schema_version": insert_statement.excluded.schema_version,
                "snapshot_hash": insert_statement.excluded.snapshot_hash,
                "fetched_at": insert_statement.excluded.fetched_at,
                "expires_at": insert_statement.excluded.expires_at,
                "updated_at": insert_statement.excluded.updated_at,
            },
        ).returning(MatchTimelineRow)
        async with self._session_factory.begin() as session:
            row = (await session.execute(upsert_statement)).scalar_one()
        return _to_record(row)


def _validate_timezone(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _to_record(row: MatchTimelineRow) -> TimelineCacheRecord:
    return TimelineCacheRecord(
        platform=Platform(row.platform),
        match_id=row.match_id,
        result_status=row.result_status,  # type: ignore[arg-type]
        normalized_snapshot=row.normalized_snapshot,
        schema_version=row.schema_version,
        snapshot_hash=row.snapshot_hash,
        fetched_at=row.fetched_at,
        expires_at=row.expires_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
