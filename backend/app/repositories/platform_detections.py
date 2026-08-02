from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.routing import Platform, ordered_platforms
from app.models.platform_detection import PlatformDetectionRow


class DetectionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class PlatformDetectionRecord:
    id: UUID
    game_name_key: str
    tag_line_key: str
    canonical_game_name: str | None
    canonical_tag_line: str | None
    puuid: str | None
    status: DetectionStatus
    candidate_platforms: tuple[Platform, ...]
    fetched_at: datetime
    expires_at: datetime
    confirmation_expires_at: datetime | None

    def __post_init__(self) -> None:
        _validate_timezone(self.fetched_at, "fetched_at")
        _validate_timezone(self.expires_at, "expires_at")
        if self.confirmation_expires_at is not None:
            _validate_timezone(self.confirmation_expires_at, "confirmation_expires_at")

        for platform in self.candidate_platforms:
            if not isinstance(platform, Platform):
                raise ValueError(f"invalid candidate platform: {platform!r}")

        if self.status is DetectionStatus.RESOLVED:
            if self.puuid is None:
                raise ValueError("resolved detection requires puuid")
            if len(self.candidate_platforms) != 1:
                raise ValueError("resolved detection requires exactly one candidate platform")
            if self.confirmation_expires_at is not None:
                raise ValueError("resolved detection must not set confirmation_expires_at")
            return

        if self.status is DetectionStatus.AMBIGUOUS:
            if self.puuid is None:
                raise ValueError("ambiguous detection requires puuid")
            if len(self.candidate_platforms) < 2:
                raise ValueError("ambiguous detection requires at least two candidate platforms")
            if self.confirmation_expires_at is None:
                raise ValueError("ambiguous detection requires confirmation_expires_at")
            return

        if self.status is DetectionStatus.NOT_FOUND:
            if self.puuid is not None:
                raise ValueError("not_found detection must not set puuid")
            if self.candidate_platforms:
                raise ValueError("not_found detection must not set candidate platforms")
            if self.confirmation_expires_at is not None:
                raise ValueError("not_found detection must not set confirmation_expires_at")
            if self.canonical_game_name is not None or self.canonical_tag_line is not None:
                raise ValueError("not_found detection must not set canonical riot id fields")
            return

        raise ValueError(f"unsupported detection status: {self.status!r}")


class PlatformDetectionRepository(Protocol):
    async def get_fresh(
        self, *, game_name_key: str, tag_line_key: str, now: datetime
    ) -> PlatformDetectionRecord | None: ...

    async def get_for_confirmation(
        self, *, detection_id: UUID, now: datetime
    ) -> PlatformDetectionRecord | None: ...

    async def upsert(self, record: PlatformDetectionRecord) -> PlatformDetectionRecord: ...

    async def delete(self, *, detection_id: UUID) -> None: ...


class SqlPlatformDetectionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_fresh(
        self, *, game_name_key: str, tag_line_key: str, now: datetime
    ) -> PlatformDetectionRecord | None:
        _validate_timezone(now, "now")
        statement = select(PlatformDetectionRow).where(
            PlatformDetectionRow.game_name_key == game_name_key,
            PlatformDetectionRow.tag_line_key == tag_line_key,
            PlatformDetectionRow.expires_at > now,
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
        return _to_record(row) if row is not None else None

    async def get_for_confirmation(
        self, *, detection_id: UUID, now: datetime
    ) -> PlatformDetectionRecord | None:
        _validate_timezone(now, "now")
        statement = select(PlatformDetectionRow).where(
            PlatformDetectionRow.id == detection_id,
            PlatformDetectionRow.expires_at > now,
            PlatformDetectionRow.confirmation_expires_at.is_not(None),
            PlatformDetectionRow.confirmation_expires_at > now,
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
        return _to_record(row) if row is not None else None

    async def upsert(self, record: PlatformDetectionRecord) -> PlatformDetectionRecord:
        ordered_candidates = _ordered_candidates(record.candidate_platforms)
        normalized = PlatformDetectionRecord(
            id=record.id,
            game_name_key=record.game_name_key,
            tag_line_key=record.tag_line_key,
            canonical_game_name=record.canonical_game_name,
            canonical_tag_line=record.canonical_tag_line,
            puuid=record.puuid,
            status=record.status,
            candidate_platforms=ordered_candidates,
            fetched_at=record.fetched_at,
            expires_at=record.expires_at,
            confirmation_expires_at=record.confirmation_expires_at,
        )
        values = {
            "id": normalized.id,
            "game_name_key": normalized.game_name_key,
            "tag_line_key": normalized.tag_line_key,
            "canonical_game_name": normalized.canonical_game_name,
            "canonical_tag_line": normalized.canonical_tag_line,
            "puuid": normalized.puuid,
            "result_status": normalized.status.value,
            "candidate_platforms": [platform.value for platform in normalized.candidate_platforms],
            "fetched_at": normalized.fetched_at,
            "expires_at": normalized.expires_at,
            "confirmation_expires_at": normalized.confirmation_expires_at,
            "created_at": normalized.fetched_at,
            "updated_at": normalized.fetched_at,
        }
        statement = insert(PlatformDetectionRow).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[
                PlatformDetectionRow.game_name_key,
                PlatformDetectionRow.tag_line_key,
            ],
            set_={
                "canonical_game_name": statement.excluded.canonical_game_name,
                "canonical_tag_line": statement.excluded.canonical_tag_line,
                "puuid": statement.excluded.puuid,
                "result_status": statement.excluded.result_status,
                "candidate_platforms": statement.excluded.candidate_platforms,
                "fetched_at": statement.excluded.fetched_at,
                "expires_at": statement.excluded.expires_at,
                "confirmation_expires_at": statement.excluded.confirmation_expires_at,
                "updated_at": statement.excluded.updated_at,
            },
        ).returning(PlatformDetectionRow)
        async with self._session_factory.begin() as session:
            row = (await session.execute(statement)).scalar_one()
        return _to_record(row)

    async def delete(self, *, detection_id: UUID) -> None:
        statement = delete(PlatformDetectionRow).where(PlatformDetectionRow.id == detection_id)
        async with self._session_factory.begin() as session:
            await session.execute(statement)


def _validate_timezone(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _ordered_candidates(candidates: tuple[Platform, ...]) -> tuple[Platform, ...]:
    order = {platform: index for index, platform in enumerate(ordered_platforms())}
    return tuple(sorted(candidates, key=lambda platform: order[platform]))


def _to_record(row: PlatformDetectionRow) -> PlatformDetectionRecord:
    platforms = tuple(Platform(value) for value in row.candidate_platforms)
    return PlatformDetectionRecord(
        id=row.id,
        game_name_key=row.game_name_key,
        tag_line_key=row.tag_line_key,
        canonical_game_name=row.canonical_game_name,
        canonical_tag_line=row.canonical_tag_line,
        puuid=row.puuid,
        status=DetectionStatus(row.result_status),
        candidate_platforms=_ordered_candidates(platforms),
        fetched_at=row.fetched_at,
        expires_at=row.expires_at,
        confirmation_expires_at=row.confirmation_expires_at,
    )
