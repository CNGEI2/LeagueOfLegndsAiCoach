from collections.abc import Mapping, Set
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, and_, delete, or_, select, true, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.replay import ReplayArtifactRow, ReplayJobRow, ReplayUploadRow
from app.services.replays.domain import ReplayJobKind, ReplayJobStatus, ReplayStatus

_ACTIVE_JOB_STATUSES = (
    ReplayJobStatus.PENDING.value,
    ReplayJobStatus.RUNNING.value,
    ReplayJobStatus.RETRY_SCHEDULED.value,
)
_CLAIMABLE_JOB_STATUSES = (
    ReplayJobStatus.PENDING.value,
    ReplayJobStatus.RETRY_SCHEDULED.value,
)
_TOMBSTONE_RETENTION = timedelta(days=7)
_FAILED_FULL_DELETE_AFTER = timedelta(days=7)
_SENSITIVE_SCRUB_FIELDS = (
    "selected_puuid",
    "token_digest",
    "original_filename",
    "declared_content_type",
    "source_object_key",
    "normalized_object_key",
    "source_sha256",
    "width",
    "height",
    "frame_rate_numerator",
    "frame_rate_denominator",
    "actual_size_bytes",
    "actual_container",
    "source_duration_ms",
    "normalized_duration_ms",
)


class ReplayStateConflict(Exception):
    """Optimistic replay state/version precondition failed."""


class ReplayActiveJobConflict(Exception):
    """A replay already has an active job of the requested kind."""


class ReplayArtifactConflict(Exception):
    """An artifact already exists for the timestamp with a different content hash."""


class ReplayRepository(Protocol):
    async def create(self, row: ReplayUploadRow) -> ReplayUploadRow: ...

    async def get(self, replay_id: UUID) -> ReplayUploadRow | None: ...

    async def transition(
        self,
        *,
        replay_id: UUID,
        expected_statuses: Set[ReplayStatus],
        expected_version: int,
        status: ReplayStatus,
        values: Mapping[str, Any],
    ) -> ReplayUploadRow: ...

    async def queue_process_job(
        self,
        *,
        replay_id: UUID,
        expected_statuses: Set[ReplayStatus],
        expected_version: int,
        status: ReplayStatus = ReplayStatus.QUEUED,
        values: Mapping[str, Any],
        available_at: datetime,
        max_attempts: int = 3,
    ) -> ReplayUploadRow: ...

    async def scrub_deleted(self, replay_id: UUID, *, now: datetime) -> ReplayUploadRow: ...


class ReplayJobRepository(Protocol):
    async def enqueue(
        self,
        *,
        replay_id: UUID,
        kind: ReplayJobKind,
        available_at: datetime,
        max_attempts: int = 3,
    ) -> ReplayJobRow: ...

    async def enqueue_idempotent(
        self,
        *,
        replay_id: UUID,
        kind: ReplayJobKind,
        available_at: datetime,
        max_attempts: int = 3,
    ) -> ReplayJobRow: ...

    async def claim_next(self, *, worker_id: str, now: datetime) -> ReplayJobRow | None: ...

    async def heartbeat(self, job_id: UUID, *, worker_id: str, now: datetime) -> None: ...

    async def succeed(self, job_id: UUID, *, now: datetime) -> ReplayJobRow: ...

    async def fail(
        self,
        job_id: UUID,
        *,
        error_code: str,
        now: datetime,
        available_at: datetime | None,
    ) -> ReplayJobRow: ...

    async def cancel(self, job_id: UUID, *, now: datetime) -> ReplayJobRow: ...

    async def recover_stale(
        self,
        *,
        heartbeat_before: datetime,
        available_at: datetime,
        now: datetime,
        source_delete_after: datetime | None = None,
    ) -> int: ...

    async def enqueue_due_retention(self, now: datetime) -> int: ...


class ReplayArtifactRepository(Protocol):
    async def upsert(self, row: ReplayArtifactRow) -> ReplayArtifactRow: ...

    async def list_for_replay(self, replay_id: UUID) -> list[ReplayArtifactRow]: ...

    async def delete_rows(self, replay_id: UUID) -> int: ...


class SqlReplayRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, row: ReplayUploadRow) -> ReplayUploadRow:
        async with self._session_factory.begin() as session:
            session.add(row)
            await session.flush()
            await session.refresh(row)
            session.expunge(row)
            return row

    async def get(self, replay_id: UUID) -> ReplayUploadRow | None:
        async with self._session_factory() as session:
            row = await session.get(ReplayUploadRow, replay_id)
            if row is not None:
                session.expunge(row)
            return row

    async def transition(
        self,
        *,
        replay_id: UUID,
        expected_statuses: Set[ReplayStatus],
        expected_version: int,
        status: ReplayStatus,
        values: Mapping[str, Any],
    ) -> ReplayUploadRow:
        now = datetime.now(UTC)
        updates: dict[str, Any] = {
            "status": status.value,
            "version": expected_version + 1,
            "updated_at": now,
            **values,
        }
        statement = (
            update(ReplayUploadRow)
            .where(
                ReplayUploadRow.id == replay_id,
                ReplayUploadRow.version == expected_version,
                ReplayUploadRow.status.in_([item.value for item in expected_statuses]),
            )
            .values(**updates)
            .returning(ReplayUploadRow)
        )
        async with self._session_factory.begin() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
            if row is None:
                raise ReplayStateConflict("replay state or version precondition failed")
            session.expunge(row)
            return row

    async def queue_process_job(
        self,
        *,
        replay_id: UUID,
        expected_statuses: Set[ReplayStatus],
        expected_version: int,
        status: ReplayStatus = ReplayStatus.QUEUED,
        values: Mapping[str, Any],
        available_at: datetime,
        max_attempts: int = 3,
    ) -> ReplayUploadRow:
        """Atomically transition the replay row and enqueue its PROCESS job.

        Both writes happen in the same PostgreSQL transaction so a status
        transition can never be committed without its job (or vice versa).
        The partial unique index on active jobs still guards against
        duplicate active PROCESS jobs for the same replay.
        """
        now = datetime.now(UTC)
        updates: dict[str, Any] = {
            "status": status.value,
            "version": expected_version + 1,
            "updated_at": now,
            **values,
        }
        statement = (
            update(ReplayUploadRow)
            .where(
                ReplayUploadRow.id == replay_id,
                ReplayUploadRow.version == expected_version,
                ReplayUploadRow.status.in_([item.value for item in expected_statuses]),
            )
            .values(**updates)
            .returning(ReplayUploadRow)
        )
        job_row = ReplayJobRow(
            id=uuid4(),
            replay_id=replay_id,
            kind=ReplayJobKind.PROCESS.value,
            status=ReplayJobStatus.PENDING.value,
            attempt_count=0,
            max_attempts=max_attempts,
            available_at=available_at,
            created_at=now,
            updated_at=now,
        )
        async with self._session_factory.begin() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
            if row is None:
                raise ReplayStateConflict("replay state or version precondition failed")
            session.add(job_row)
            try:
                await session.flush()
            except IntegrityError as error:
                if _is_active_job_integrity_error(error):
                    raise ReplayActiveJobConflict("an active process job already exists") from error
                raise
            session.expunge(row)
            return row

    async def scrub_deleted(self, replay_id: UUID, *, now: datetime) -> ReplayUploadRow:
        updates: dict[str, Any] = {field: None for field in _SENSITIVE_SCRUB_FIELDS}
        updates.update(
            {
                "status": ReplayStatus.DELETED.value,
                "deleted_at": now,
                "updated_at": now,
                "processing_stage": None,
                "error_code": None,
                "error_retryable": None,
                "available_game_time_start_ms": None,
                "available_game_time_end_ms": None,
                "warning_codes": [],
            }
        )
        statement = (
            update(ReplayUploadRow)
            .where(ReplayUploadRow.id == replay_id)
            .values(**updates)
            .returning(ReplayUploadRow)
        )
        async with self._session_factory.begin() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
            if row is None:
                raise ReplayStateConflict("replay not found for scrub")
            session.expunge(row)
            return row


class SqlReplayJobRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def enqueue(
        self,
        *,
        replay_id: UUID,
        kind: ReplayJobKind,
        available_at: datetime,
        max_attempts: int = 3,
    ) -> ReplayJobRow:
        now = datetime.now(UTC)
        row = ReplayJobRow(
            id=uuid4(),
            replay_id=replay_id,
            kind=kind.value,
            status=ReplayJobStatus.PENDING.value,
            attempt_count=0,
            max_attempts=max_attempts,
            available_at=available_at,
            created_at=now,
            updated_at=now,
        )
        async with self._session_factory.begin() as session:
            session.add(row)
            await session.flush()
            await session.refresh(row)
            session.expunge(row)
            return row

    async def enqueue_idempotent(
        self,
        *,
        replay_id: UUID,
        kind: ReplayJobKind,
        available_at: datetime,
        max_attempts: int = 3,
    ) -> ReplayJobRow:
        """Enqueue a job, tolerating a concurrent enqueue of the same kind.

        The partial unique index on active jobs (`uq_replay_active_job`)
        guards against two active jobs of the same kind existing for the same
        replay at once. Some callers (e.g. a user's request_delete racing the
        retention sweep's enqueue_due_retention) can legitimately both try to
        enqueue a DELETE_ALL job for the same replay; whichever loses the race
        should observe success by returning the job that already won, rather
        than propagating an IntegrityError.
        """
        try:
            return await self.enqueue(
                replay_id=replay_id,
                kind=kind,
                available_at=available_at,
                max_attempts=max_attempts,
            )
        except IntegrityError:
            existing = await self._get_active_job(replay_id=replay_id, kind=kind)
            if existing is None:
                raise
            return existing

    async def _get_active_job(self, *, replay_id: UUID, kind: ReplayJobKind) -> ReplayJobRow | None:
        statement = select(ReplayJobRow).where(
            ReplayJobRow.replay_id == replay_id,
            ReplayJobRow.kind == kind.value,
            ReplayJobRow.status.in_(_ACTIVE_JOB_STATUSES),
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
            if row is not None:
                session.expunge(row)
            return row

    async def claim_next(self, *, worker_id: str, now: datetime) -> ReplayJobRow | None:
        statement = (
            select(ReplayJobRow)
            .where(
                ReplayJobRow.status.in_(_CLAIMABLE_JOB_STATUSES),
                ReplayJobRow.available_at <= now,
            )
            .order_by(ReplayJobRow.available_at, ReplayJobRow.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        async with self._session_factory.begin() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
            if row is None:
                return None
            row.status = ReplayJobStatus.RUNNING.value
            row.claimed_at = now
            row.heartbeat_at = now
            row.worker_id = worker_id
            row.attempt_count += 1
            row.updated_at = now
            await session.flush()
            await session.refresh(row)
            session.expunge(row)
            return row

    async def heartbeat(self, job_id: UUID, *, worker_id: str, now: datetime) -> None:
        statement = (
            update(ReplayJobRow)
            .where(
                ReplayJobRow.id == job_id,
                ReplayJobRow.worker_id == worker_id,
                ReplayJobRow.status == ReplayJobStatus.RUNNING.value,
            )
            .values(heartbeat_at=now, updated_at=now)
        )
        async with self._session_factory.begin() as session:
            await session.execute(statement)

    async def succeed(self, job_id: UUID, *, now: datetime) -> ReplayJobRow:
        statement = (
            update(ReplayJobRow)
            .where(ReplayJobRow.id == job_id)
            .values(
                status=ReplayJobStatus.SUCCEEDED.value,
                finished_at=now,
                updated_at=now,
                worker_id=None,
                claimed_at=None,
                heartbeat_at=None,
            )
            .returning(ReplayJobRow)
        )
        async with self._session_factory.begin() as session:
            row = (await session.execute(statement)).scalar_one()
            session.expunge(row)
            return row

    async def fail(
        self,
        job_id: UUID,
        *,
        error_code: str,
        now: datetime,
        available_at: datetime | None,
    ) -> ReplayJobRow:
        async with self._session_factory.begin() as session:
            row = await session.get(ReplayJobRow, job_id)
            if row is None:
                raise ReplayStateConflict("job not found")
            row.last_error_code = error_code
            row.updated_at = now
            row.worker_id = None
            row.claimed_at = None
            row.heartbeat_at = None
            if available_at is not None and row.attempt_count < row.max_attempts:
                row.status = ReplayJobStatus.RETRY_SCHEDULED.value
                row.available_at = available_at
                row.finished_at = None
            else:
                row.status = ReplayJobStatus.FAILED.value
                row.finished_at = now
            await session.flush()
            await session.refresh(row)
            session.expunge(row)
            return row

    async def cancel(self, job_id: UUID, *, now: datetime) -> ReplayJobRow:
        statement = (
            update(ReplayJobRow)
            .where(ReplayJobRow.id == job_id)
            .values(
                status=ReplayJobStatus.CANCELLED.value,
                finished_at=now,
                updated_at=now,
                worker_id=None,
                claimed_at=None,
                heartbeat_at=None,
            )
            .returning(ReplayJobRow)
        )
        async with self._session_factory.begin() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
            if row is None:
                raise ReplayStateConflict("job not found")
            session.expunge(row)
            return row

    async def recover_stale(
        self,
        *,
        heartbeat_before: datetime,
        available_at: datetime,
        now: datetime,
        source_delete_after: datetime | None = None,
    ) -> int:
        """Recover stale jobs and reconcile their PROCESS replay state.

        Job recovery and the corresponding replay transition share a
        transaction: a replay cannot remain transcoding/extracting after its
        only PROCESS job became retry-scheduled or terminally failed.
        """
        statement = (
            select(ReplayJobRow)
            .where(
                ReplayJobRow.status == ReplayJobStatus.RUNNING.value,
                ReplayJobRow.heartbeat_at.is_not(None),
                ReplayJobRow.heartbeat_at < heartbeat_before,
            )
            .with_for_update(skip_locked=True)
        )
        async with self._session_factory.begin() as session:
            jobs = list((await session.execute(statement)).scalars())
            for job in jobs:
                replay = await session.get(
                    ReplayUploadRow,
                    job.replay_id,
                    with_for_update=True,
                )
                if (
                    job.kind == ReplayJobKind.PROCESS.value
                    and replay is not None
                    and replay.status in {ReplayStatus.DELETING.value, ReplayStatus.DELETED.value}
                ):
                    job.status = ReplayJobStatus.CANCELLED.value
                    job.finished_at = now
                else:
                    can_retry = job.attempt_count < job.max_attempts
                    job.status = (
                        ReplayJobStatus.RETRY_SCHEDULED.value
                        if can_retry
                        else ReplayJobStatus.FAILED.value
                    )
                    job.available_at = available_at if can_retry else job.available_at
                    job.finished_at = None if can_retry else now

                    if job.kind == ReplayJobKind.PROCESS.value and replay is not None:
                        _sync_replay_after_stale_process_job(
                            replay,
                            retry_scheduled=can_retry,
                            now=now,
                            source_delete_after=source_delete_after,
                        )

                job.last_error_code = "REPLAY_WORKER_STALE"
                job.worker_id = None
                job.claimed_at = None
                job.heartbeat_at = None
                job.updated_at = now
            await session.flush()
        return len(jobs)

    async def enqueue_due_retention(self, now: datetime) -> int:
        created = 0
        async with self._session_factory.begin() as session:
            await session.execute(
                delete(ReplayUploadRow).where(
                    ReplayUploadRow.status == ReplayStatus.DELETED.value,
                    ReplayUploadRow.deleted_at.is_not(None),
                    ReplayUploadRow.deleted_at <= now - _TOMBSTONE_RETENTION,
                )
            )

            delete_all_rows = list(
                (
                    await session.execute(
                        select(ReplayUploadRow)
                        .where(_delete_all_due_predicate(now))
                        .with_for_update(skip_locked=True)
                    )
                ).scalars()
            )
            delete_all_ids = {row.id for row in delete_all_rows}
            for row in delete_all_rows:
                if await _has_active_job(session, row.id, ReplayJobKind.DELETE_ALL):
                    continue
                session.add(
                    _new_job(
                        replay_id=row.id,
                        kind=ReplayJobKind.DELETE_ALL,
                        available_at=now,
                        now=now,
                    )
                )
                created += 1

            exclude_ids = ReplayUploadRow.id.not_in(delete_all_ids) if delete_all_ids else true()
            source_rows = list(
                (
                    await session.execute(
                        select(ReplayUploadRow)
                        .where(
                            ReplayUploadRow.source_delete_after.is_not(None),
                            ReplayUploadRow.source_delete_after <= now,
                            exclude_ids,
                            ReplayUploadRow.status.not_in(
                                (
                                    ReplayStatus.DELETED.value,
                                    ReplayStatus.DELETING.value,
                                )
                            ),
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).scalars()
            )
            for row in source_rows:
                if await _has_active_job(session, row.id, ReplayJobKind.DELETE_SOURCE):
                    continue
                if await _has_active_job(session, row.id, ReplayJobKind.DELETE_ALL):
                    continue
                session.add(
                    _new_job(
                        replay_id=row.id,
                        kind=ReplayJobKind.DELETE_SOURCE,
                        available_at=now,
                        now=now,
                    )
                )
                created += 1
        return created


class SqlReplayArtifactRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert(self, row: ReplayArtifactRow) -> ReplayArtifactRow:
        statement = select(ReplayArtifactRow).where(
            ReplayArtifactRow.replay_id == row.replay_id,
            ReplayArtifactRow.kind == row.kind,
            ReplayArtifactRow.game_time_ms == row.game_time_ms,
            ReplayArtifactRow.video_time_ms == row.video_time_ms,
        )
        async with self._session_factory.begin() as session:
            existing = (await session.execute(statement)).scalar_one_or_none()
            if existing is not None:
                if existing.sha256 != row.sha256:
                    raise ReplayArtifactConflict(
                        "artifact content hash differs for the same timestamp key"
                    )
                session.expunge(existing)
                return existing
            session.add(row)
            await session.flush()
            await session.refresh(row)
            session.expunge(row)
            return row

    async def list_for_replay(self, replay_id: UUID) -> list[ReplayArtifactRow]:
        statement = (
            select(ReplayArtifactRow)
            .where(ReplayArtifactRow.replay_id == replay_id)
            .order_by(ReplayArtifactRow.game_time_ms, ReplayArtifactRow.video_time_ms)
        )
        async with self._session_factory() as session:
            rows = list((await session.execute(statement)).scalars())
            for row in rows:
                session.expunge(row)
            return rows

    async def delete_rows(self, replay_id: UUID) -> int:
        statement = delete(ReplayArtifactRow).where(ReplayArtifactRow.replay_id == replay_id)
        async with self._session_factory.begin() as session:
            result = await session.execute(statement)
        return _rowcount(result)


def _delete_all_due_predicate(now: datetime) -> ColumnElement[bool]:
    failed_cutoff = now - _FAILED_FULL_DELETE_AFTER
    return or_(
        and_(
            ReplayUploadRow.derived_delete_after.is_not(None),
            ReplayUploadRow.derived_delete_after <= now,
        ),
        ReplayUploadRow.status == ReplayStatus.DELETING.value,
        and_(
            ReplayUploadRow.upload_expires_at <= now,
            ReplayUploadRow.status.in_(
                (
                    ReplayStatus.CREATED.value,
                    ReplayStatus.UPLOADED.value,
                    ReplayStatus.EXPIRED.value,
                )
            ),
        ),
        and_(
            ReplayUploadRow.status == ReplayStatus.FAILED.value,
            ReplayUploadRow.processing_finished_at.is_not(None),
            ReplayUploadRow.processing_finished_at <= failed_cutoff,
        ),
    )


async def _has_active_job(
    session: AsyncSession,
    replay_id: UUID,
    kind: ReplayJobKind,
) -> bool:
    statement = select(ReplayJobRow.id).where(
        ReplayJobRow.replay_id == replay_id,
        ReplayJobRow.kind == kind.value,
        ReplayJobRow.status.in_(_ACTIVE_JOB_STATUSES),
    )
    return (await session.execute(statement)).scalar_one_or_none() is not None


def _new_job(
    *,
    replay_id: UUID,
    kind: ReplayJobKind,
    available_at: datetime,
    now: datetime,
) -> ReplayJobRow:
    return ReplayJobRow(
        id=uuid4(),
        replay_id=replay_id,
        kind=kind.value,
        status=ReplayJobStatus.PENDING.value,
        attempt_count=0,
        max_attempts=3,
        available_at=available_at,
        created_at=now,
        updated_at=now,
    )


def _sync_replay_after_stale_process_job(
    replay: ReplayUploadRow,
    *,
    retry_scheduled: bool,
    now: datetime,
    source_delete_after: datetime | None,
) -> None:
    """Mirror stale PROCESS job recovery onto its replay lifecycle row."""
    replay.status = ReplayStatus.QUEUED.value if retry_scheduled else ReplayStatus.FAILED.value
    replay.processing_stage = "queued" if retry_scheduled else "failed"
    replay.error_code = "REPLAY_WORKER_STALE"
    replay.error_retryable = True
    replay.processing_finished_at = None if retry_scheduled else now
    if not retry_scheduled and source_delete_after is not None:
        replay.source_delete_after = source_delete_after
    replay.updated_at = now
    replay.version += 1


def _rowcount(result: object) -> int:
    return cast(CursorResult[object], result).rowcount


def _is_active_job_integrity_error(error: IntegrityError) -> bool:
    """Restrict conflict recovery to the active-job partial unique index.

    Other integrity failures still represent unexpected persistence failures
    and must retain their original error path rather than being mislabeled as
    a retry conflict.
    """
    return "uq_replay_active_job" in str(error.orig)
