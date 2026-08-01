from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.routing import Platform
from app.models.replay import ReplayArtifactRow, ReplayJobRow, ReplayUploadRow
from app.repositories.matches import SqlMatchRepository
from app.repositories.replays import (
    ReplayArtifactConflict,
    ReplayStateConflict,
    SqlReplayArtifactRepository,
    SqlReplayJobRepository,
    SqlReplayRepository,
)
from app.schemas.domain import MatchSnapshot, ParticipantSnapshot
from app.services.replays.domain import (
    ReplayArtifactKind,
    ReplayJobKind,
    ReplayJobStatus,
    ReplayStatus,
)

pytestmark = pytest.mark.integration


def _now() -> datetime:
    return datetime.now(UTC)


def make_replay(**overrides: object) -> ReplayUploadRow:
    now = _now()
    values: dict[str, object] = {
        "id": uuid4(),
        "match_id": "NA1_1",
        "platform": Platform.NA1.value,
        "selected_puuid": "selected-puuid",
        "match_duration_ms": 1_800_000,
        "status": ReplayStatus.CREATED.value,
        "progress_percent": 0,
        "token_digest": "a" * 64,
        "original_filename": "owned.mp4",
        "declared_content_type": "video/mp4",
        "declared_size_bytes": 100,
        "game_time_zero_ms": 1_000,
        "rights_statement_version": "2026-08-01",
        "rights_attested_at": now,
        "upload_expires_at": now + timedelta(minutes=30),
        "warning_codes": [],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    values.update(overrides)
    return ReplayUploadRow(**values)


def make_snapshot(*, match_id: str = "NA1_replay") -> MatchSnapshot:
    return MatchSnapshot(
        match_id=match_id,
        platform=Platform.NA1,
        queue_id=420,
        game_version="16.15.1",
        started_at=datetime(2026, 7, 30, 12, tzinfo=UTC),
        duration_seconds=1800,
        participants=(
            ParticipantSnapshot(
                puuid="match-puuid",
                team_id=100,
                champion_id=103,
                role="MIDDLE",
                won=True,
                kills=8,
                deaths=2,
                assists=6,
                cs=201,
                gold_earned=14321,
                damage_to_champions=24567,
                vision_score=18,
                item_ids=(1055, 6672, 3006),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_transition_requires_expected_version(session_factory) -> None:
    repository = SqlReplayRepository(session_factory)
    created = await repository.create(make_replay())

    updated = await repository.transition(
        replay_id=created.id,
        expected_statuses={ReplayStatus.CREATED},
        expected_version=1,
        status=ReplayStatus.UPLOADED,
        values={},
    )
    assert updated.status == ReplayStatus.UPLOADED.value
    assert updated.version == 2

    with pytest.raises(ReplayStateConflict):
        await repository.transition(
            replay_id=created.id,
            expected_statuses={ReplayStatus.CREATED},
            expected_version=1,
            status=ReplayStatus.UPLOADED,
            values={},
        )


@pytest.mark.asyncio
async def test_transition_rejects_unexpected_status(session_factory) -> None:
    repository = SqlReplayRepository(session_factory)
    created = await repository.create(make_replay(status=ReplayStatus.READY.value))

    with pytest.raises(ReplayStateConflict):
        await repository.transition(
            replay_id=created.id,
            expected_statuses={ReplayStatus.QUEUED},
            expected_version=1,
            status=ReplayStatus.PROBING,
            values={},
        )


@pytest.mark.asyncio
async def test_get_returns_created_replay(session_factory) -> None:
    repository = SqlReplayRepository(session_factory)
    created = await repository.create(make_replay(match_id="NA1_get"))
    loaded = await repository.get(created.id)
    assert loaded is not None
    assert loaded.id == created.id
    assert loaded.match_id == "NA1_get"
    assert await repository.get(uuid4()) is None


@pytest.mark.asyncio
async def test_scrub_deleted_clears_sensitive_fields_and_keeps_tombstone(
    session_factory,
) -> None:
    now = _now()
    repository = SqlReplayRepository(session_factory)
    created = await repository.create(
        make_replay(
            status=ReplayStatus.DELETING.value,
            selected_puuid="private-puuid",
            token_digest="b" * 64,
            original_filename="secret.mp4",
            declared_content_type="video/mp4",
            source_object_key="source/abc/input",
            normalized_object_key="normalized/abc/output",
            source_sha256="c" * 64,
            width=1280,
            height=720,
            frame_rate_numerator=30,
            frame_rate_denominator=1,
            actual_size_bytes=2048,
            actual_container="mp4",
            source_duration_ms=1_200_000,
            normalized_duration_ms=1_200_000,
        )
    )

    scrubbed = await repository.scrub_deleted(created.id, now=now)
    assert scrubbed.status == ReplayStatus.DELETED.value
    assert scrubbed.deleted_at == now
    assert scrubbed.id == created.id
    assert scrubbed.selected_puuid is None
    assert scrubbed.token_digest is None
    assert scrubbed.original_filename is None
    assert scrubbed.declared_content_type is None
    assert scrubbed.source_object_key is None
    assert scrubbed.normalized_object_key is None
    assert scrubbed.source_sha256 is None
    assert scrubbed.width is None
    assert scrubbed.height is None
    assert scrubbed.frame_rate_numerator is None
    assert scrubbed.frame_rate_denominator is None
    assert scrubbed.actual_size_bytes is None
    assert scrubbed.actual_container is None
    assert scrubbed.source_duration_ms is None
    assert scrubbed.normalized_duration_ms is None
    assert scrubbed.match_id == created.match_id
    assert scrubbed.declared_size_bytes == created.declared_size_bytes


@pytest.mark.asyncio
async def test_claim_next_claims_earliest_available_job(session_factory) -> None:
    now = _now()
    replays = SqlReplayRepository(session_factory)
    jobs = SqlReplayJobRepository(session_factory)
    first_replay = await replays.create(make_replay())
    second_replay = await replays.create(make_replay(match_id="NA1_2"))
    later = await jobs.enqueue(
        replay_id=second_replay.id,
        kind=ReplayJobKind.PROCESS,
        available_at=now + timedelta(seconds=1),
    )
    earlier = await jobs.enqueue(
        replay_id=first_replay.id,
        kind=ReplayJobKind.PROCESS,
        available_at=now - timedelta(seconds=1),
    )

    claimed = await jobs.claim_next(worker_id="worker-a", now=now)
    assert claimed is not None
    assert claimed.id == earlier.id
    assert claimed.status == ReplayJobStatus.RUNNING.value
    assert claimed.worker_id == "worker-a"
    assert claimed.attempt_count == 1
    assert claimed.claimed_at == now
    assert claimed.heartbeat_at == now
    assert claimed.id != later.id


@pytest.mark.asyncio
async def test_duplicate_active_job_enqueue_is_blocked(session_factory) -> None:
    now = _now()
    replays = SqlReplayRepository(session_factory)
    jobs = SqlReplayJobRepository(session_factory)
    replay = await replays.create(make_replay())
    await jobs.enqueue(
        replay_id=replay.id,
        kind=ReplayJobKind.PROCESS,
        available_at=now,
    )
    with pytest.raises(IntegrityError):
        await jobs.enqueue(
            replay_id=replay.id,
            kind=ReplayJobKind.PROCESS,
            available_at=now,
        )


@pytest.mark.asyncio
async def test_heartbeat_succeed_and_fail_update_job_lifecycle(session_factory) -> None:
    now = _now()
    replays = SqlReplayRepository(session_factory)
    jobs = SqlReplayJobRepository(session_factory)
    replay = await replays.create(make_replay())
    await jobs.enqueue(replay_id=replay.id, kind=ReplayJobKind.PROCESS, available_at=now)
    claimed = await jobs.claim_next(worker_id="worker-b", now=now)
    assert claimed is not None

    heartbeat_at = now + timedelta(seconds=30)
    await jobs.heartbeat(claimed.id, worker_id="worker-b", now=heartbeat_at)
    async with session_factory() as session:
        row = (
            await session.execute(select(ReplayJobRow).where(ReplayJobRow.id == claimed.id))
        ).scalar_one()
    assert row.heartbeat_at == heartbeat_at

    succeeded = await jobs.succeed(claimed.id, now=heartbeat_at + timedelta(seconds=1))
    assert succeeded.status == ReplayJobStatus.SUCCEEDED.value
    assert succeeded.finished_at == heartbeat_at + timedelta(seconds=1)
    assert succeeded.worker_id is None

    second_replay = await replays.create(make_replay(match_id="NA1_fail"))
    await jobs.enqueue(
        replay_id=second_replay.id,
        kind=ReplayJobKind.PROCESS,
        available_at=now,
        max_attempts=3,
    )
    failing = await jobs.claim_next(worker_id="worker-c", now=now)
    assert failing is not None
    retry_at = now + timedelta(minutes=1)
    scheduled = await jobs.fail(
        failing.id,
        error_code="REPLAY_STORAGE_UNAVAILABLE",
        now=now,
        available_at=retry_at,
    )
    assert scheduled.status == ReplayJobStatus.RETRY_SCHEDULED.value
    assert scheduled.available_at == retry_at
    assert scheduled.last_error_code == "REPLAY_STORAGE_UNAVAILABLE"
    assert scheduled.worker_id is None

    reclaimed = await jobs.claim_next(worker_id="worker-c", now=retry_at)
    assert reclaimed is not None
    assert reclaimed.attempt_count == 2
    permanent = await jobs.fail(
        reclaimed.id,
        error_code="REPLAY_MEDIA_UNSUPPORTED",
        now=retry_at,
        available_at=None,
    )
    assert permanent.status == ReplayJobStatus.FAILED.value
    assert permanent.finished_at == retry_at
    assert permanent.last_error_code == "REPLAY_MEDIA_UNSUPPORTED"


@pytest.mark.asyncio
async def test_recover_stale_reschedules_expired_running_jobs(session_factory) -> None:
    now = _now()
    replays = SqlReplayRepository(session_factory)
    jobs = SqlReplayJobRepository(session_factory)
    replay = await replays.create(make_replay())
    claimed_at = now - timedelta(minutes=10)
    await jobs.enqueue(
        replay_id=replay.id,
        kind=ReplayJobKind.PROCESS,
        available_at=claimed_at,
    )
    claimed = await jobs.claim_next(worker_id="stale-worker", now=claimed_at)
    assert claimed is not None

    available_at = now + timedelta(minutes=2)
    recovered = await jobs.recover_stale(
        heartbeat_before=now - timedelta(minutes=5),
        available_at=available_at,
        now=now,
    )
    assert recovered == 1
    async with session_factory() as session:
        row = (
            await session.execute(select(ReplayJobRow).where(ReplayJobRow.id == claimed.id))
        ).scalar_one()
    assert row.status == ReplayJobStatus.RETRY_SCHEDULED.value
    assert row.worker_id is None
    assert row.claimed_at is None
    assert row.heartbeat_at is None
    assert row.available_at == available_at


@pytest.mark.asyncio
async def test_artifact_upsert_is_idempotent_for_same_hash_and_conflicts_on_mismatch(
    session_factory,
) -> None:
    now = _now()
    replays = SqlReplayRepository(session_factory)
    artifacts = SqlReplayArtifactRepository(session_factory)
    replay = await replays.create(make_replay(status=ReplayStatus.READY.value))
    first = await artifacts.upsert(
        ReplayArtifactRow(
            id=uuid4(),
            replay_id=replay.id,
            kind=ReplayArtifactKind.ANCHOR_FRAME.value,
            game_time_ms=0,
            video_time_ms=1_000,
            object_key="frames/a.jpg",
            sha256="d" * 64,
            media_type="image/jpeg",
            size_bytes=100,
            width=1280,
            height=720,
            created_at=now,
        )
    )
    same = await artifacts.upsert(
        ReplayArtifactRow(
            id=uuid4(),
            replay_id=replay.id,
            kind=ReplayArtifactKind.ANCHOR_FRAME.value,
            game_time_ms=0,
            video_time_ms=1_000,
            object_key="frames/a.jpg",
            sha256="d" * 64,
            media_type="image/jpeg",
            size_bytes=100,
            width=1280,
            height=720,
            created_at=now,
        )
    )
    assert same.id == first.id

    with pytest.raises(ReplayArtifactConflict):
        await artifacts.upsert(
            ReplayArtifactRow(
                id=uuid4(),
                replay_id=replay.id,
                kind=ReplayArtifactKind.ANCHOR_FRAME.value,
                game_time_ms=0,
                video_time_ms=1_000,
                object_key="frames/b.jpg",
                sha256="e" * 64,
                media_type="image/jpeg",
                size_bytes=120,
                width=1280,
                height=720,
                created_at=now,
            )
        )

    listed = await artifacts.list_for_replay(replay.id)
    assert [item.id for item in listed] == [first.id]
    assert await artifacts.delete_rows(replay.id) == 1
    assert await artifacts.list_for_replay(replay.id) == []


@pytest.mark.asyncio
async def test_enqueue_due_retention_creates_cleanup_jobs_idempotently(
    session_factory,
) -> None:
    now = _now()
    replays = SqlReplayRepository(session_factory)
    jobs = SqlReplayJobRepository(session_factory)

    source_due = await replays.create(
        make_replay(
            match_id="NA1_source",
            status=ReplayStatus.READY.value,
            source_object_key="source/ready/input",
            source_delete_after=now - timedelta(minutes=1),
            derived_delete_after=now + timedelta(days=3),
        )
    )
    derived_due = await replays.create(
        make_replay(
            match_id="NA1_derived",
            status=ReplayStatus.READY.value,
            derived_delete_after=now - timedelta(minutes=1),
        )
    )
    user_delete = await replays.create(
        make_replay(
            match_id="NA1_user",
            status=ReplayStatus.DELETING.value,
        )
    )
    expired_upload = await replays.create(
        make_replay(
            match_id="NA1_expired",
            status=ReplayStatus.CREATED.value,
            upload_expires_at=now - timedelta(minutes=1),
        )
    )
    failed_old = await replays.create(
        make_replay(
            match_id="NA1_failed",
            status=ReplayStatus.FAILED.value,
            processing_finished_at=now - timedelta(days=8),
        )
    )
    tombstone = await replays.create(
        make_replay(
            match_id="NA1_tombstone",
            status=ReplayStatus.DELETED.value,
            selected_puuid=None,
            token_digest=None,
            original_filename=None,
            declared_content_type=None,
            deleted_at=now - timedelta(days=8),
        )
    )

    created_count = await jobs.enqueue_due_retention(now)
    assert created_count >= 4

    async with session_factory() as session:
        job_rows = list((await session.execute(select(ReplayJobRow))).scalars())
        kinds_by_replay = {row.replay_id: row.kind for row in job_rows}
        assert kinds_by_replay[source_due.id] == ReplayJobKind.DELETE_SOURCE.value
        assert kinds_by_replay[derived_due.id] == ReplayJobKind.DELETE_ALL.value
        assert kinds_by_replay[user_delete.id] == ReplayJobKind.DELETE_ALL.value
        assert kinds_by_replay[expired_upload.id] == ReplayJobKind.DELETE_ALL.value
        assert kinds_by_replay[failed_old.id] == ReplayJobKind.DELETE_ALL.value
        assert await session.get(ReplayUploadRow, tombstone.id) is None

    second_count = await jobs.enqueue_due_retention(now)
    assert second_count == 0
    async with session_factory() as session:
        job_rows = list((await session.execute(select(ReplayJobRow))).scalars())
    assert len(job_rows) == 5


@pytest.mark.asyncio
async def test_get_for_replay_binding_ignores_riot_cache_ttl(session_factory) -> None:
    matches = SqlMatchRepository(session_factory)
    snapshot = make_snapshot()
    fetched_at = _now() - timedelta(days=40)
    await matches.put(snapshot, fetched_at=fetched_at)

    assert (
        await matches.get(
            platform=Platform.NA1,
            match_id=snapshot.match_id,
            fresh_after=fetched_at + timedelta(days=1),
        )
        is None
    )
    assert (
        await matches.get_for_replay_binding(
            platform=Platform.NA1,
            match_id=snapshot.match_id,
        )
        == snapshot
    )
    assert (
        await matches.get_for_replay_binding(
            platform=Platform.NA1,
            match_id="missing",
        )
        is None
    )
