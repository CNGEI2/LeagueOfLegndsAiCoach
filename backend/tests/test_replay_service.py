from __future__ import annotations

from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.routing import Platform
from app.models.replay import ReplayArtifactRow, ReplayJobRow, ReplayUploadRow
from app.schemas.domain import MatchSnapshot, ParticipantSnapshot
from app.schemas.replays import ReplayCreateRequest
from app.services.replays.domain import (
    ReplayArtifactKind,
    ReplayJobKind,
    ReplayJobStatus,
    ReplayStatus,
)
from app.services.replays.security import issue_replay_token, verify_replay_token
from app.services.replays.service import ReplayService
from app.services.replays.storage.base import (
    ReplayObjectNotFound,
    StoredObject,
    UploadTarget,
)

NOW = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
SECRET = b"x" * 32
GIB = 1024**3


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "app_env": "test",
        "replay_enabled": True,
        "replay_token_secret": "x" * 32,
        "replay_max_bytes": 4 * GIB,
        "replay_upload_expiry_seconds": 1800,
        "replay_source_retention_hours": 24,
        "replay_derived_retention_days": 7,
        "replay_storage_backend": "local",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _participant(puuid: str = "selected-player-puuid") -> ParticipantSnapshot:
    return ParticipantSnapshot(
        puuid=puuid,
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
        vision_score=21,
        item_ids=(1, 2, 3, 4, 5, 6, 0),
    )


def _snapshot(*, puuid: str = "selected-player-puuid") -> MatchSnapshot:
    return MatchSnapshot(
        match_id="NA1_1234567890",
        platform=Platform.NA1,
        queue_id=420,
        game_version="16.15.1",
        started_at=datetime(2026, 7, 30, 12, tzinfo=UTC),
        duration_seconds=1800,
        participants=(_participant(puuid),),
    )


def _create_request(**overrides: object) -> ReplayCreateRequest:
    payload: dict[str, object] = {
        "match_id": "NA1_1234567890",
        "platform": "NA1",
        "puuid": "selected-player-puuid",
        "original_filename": "recording.mp4",
        "declared_size_bytes": 1_000_000,
        "declared_content_type": "video/mp4",
        "game_time_zero_ms": 48231,
        "rights_attested": True,
        "rights_statement_version": "2026-08-01",
    }
    payload.update(overrides)
    return ReplayCreateRequest.model_validate(payload)


@dataclass
class FakeMatchRepository:
    snapshot: MatchSnapshot | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    async def get_for_replay_binding(
        self, *, platform: Platform, match_id: str
    ) -> MatchSnapshot | None:
        self.calls.append({"platform": platform, "match_id": match_id})
        return self.snapshot


@dataclass
class FakeReplayRepository:
    rows: dict[UUID, ReplayUploadRow] = field(default_factory=dict)

    async def create(self, row: ReplayUploadRow) -> ReplayUploadRow:
        self.rows[row.id] = row
        return row

    async def get(self, replay_id: UUID) -> ReplayUploadRow | None:
        return self.rows.get(replay_id)

    async def transition(
        self,
        *,
        replay_id: UUID,
        expected_statuses: Set[ReplayStatus],
        expected_version: int,
        status: ReplayStatus,
        values: Mapping[str, Any],
    ) -> ReplayUploadRow:
        row = self.rows[replay_id]
        if row.version != expected_version or ReplayStatus(row.status) not in expected_statuses:
            raise AssertionError("replay state or version precondition failed")
        for key, value in values.items():
            setattr(row, key, value)
        row.status = status.value
        row.version = expected_version + 1
        row.updated_at = NOW
        return row

    async def scrub_deleted(self, replay_id: UUID, *, now: datetime) -> ReplayUploadRow:
        raise AssertionError("scrub_deleted should not be called from ReplayService")


@dataclass
class FakeReplayJobRepository:
    jobs: list[ReplayJobRow] = field(default_factory=list)

    async def enqueue(
        self,
        *,
        replay_id: UUID,
        kind: ReplayJobKind,
        available_at: datetime,
        max_attempts: int = 3,
    ) -> ReplayJobRow:
        active = [
            job
            for job in self.jobs
            if job.replay_id == replay_id
            and job.kind == kind.value
            and job.status
            in {
                ReplayJobStatus.PENDING.value,
                ReplayJobStatus.RUNNING.value,
                ReplayJobStatus.RETRY_SCHEDULED.value,
            }
        ]
        if active:
            raise AssertionError("active job already exists")
        row = ReplayJobRow(
            id=uuid4(),
            replay_id=replay_id,
            kind=kind.value,
            status=ReplayJobStatus.PENDING.value,
            attempt_count=0,
            max_attempts=max_attempts,
            available_at=available_at,
            created_at=available_at,
            updated_at=available_at,
        )
        self.jobs.append(row)
        return row

    async def claim_next(self, *, worker_id: str, now: datetime) -> ReplayJobRow | None:
        raise AssertionError("claim_next should not be called from ReplayService")

    async def heartbeat(self, job_id: UUID, *, worker_id: str, now: datetime) -> None:
        raise AssertionError("heartbeat should not be called from ReplayService")

    async def succeed(self, job_id: UUID, *, now: datetime) -> ReplayJobRow:
        raise AssertionError("succeed should not be called from ReplayService")

    async def fail(
        self,
        job_id: UUID,
        *,
        error_code: str,
        now: datetime,
        available_at: datetime | None,
    ) -> ReplayJobRow:
        raise AssertionError("fail should not be called from ReplayService")

    async def recover_stale(
        self,
        *,
        heartbeat_before: datetime,
        available_at: datetime,
        now: datetime,
    ) -> int:
        raise AssertionError("recover_stale should not be called from ReplayService")

    async def enqueue_due_retention(self, now: datetime) -> int:
        raise AssertionError("enqueue_due_retention should not be called from ReplayService")


@dataclass
class FakeReplayArtifactRepository:
    rows: list[ReplayArtifactRow] = field(default_factory=list)

    async def upsert(self, row: ReplayArtifactRow) -> ReplayArtifactRow:
        self.rows.append(row)
        return row

    async def list_for_replay(self, replay_id: UUID) -> list[ReplayArtifactRow]:
        return [row for row in self.rows if row.replay_id == replay_id]

    async def delete_rows(self, replay_id: UUID) -> int:
        before = len(self.rows)
        self.rows = [row for row in self.rows if row.replay_id != replay_id]
        return before - len(self.rows)


@dataclass
class FakeReplayStorage:
    objects: dict[str, StoredObject] = field(default_factory=dict)
    upload_targets: list[dict[str, object]] = field(default_factory=list)

    async def create_upload_target(
        self,
        key: str,
        *,
        expires_at: datetime,
        upload_url: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> UploadTarget:
        self.upload_targets.append(
            {
                "key": key,
                "expires_at": expires_at,
                "upload_url": upload_url,
                "headers": dict(headers or {}),
            }
        )
        return UploadTarget(
            method="PUT",
            url=upload_url or f"/upload/{key}",
            headers=dict(headers or {}),
            expires_at=expires_at,
        )

    async def write_stream(self, key: str, chunks: object, max_bytes: int) -> StoredObject:
        raise AssertionError("write_stream should not be called from ReplayService")

    async def stat(self, key: str) -> StoredObject:
        if key not in self.objects:
            raise ReplayObjectNotFound(key)
        return self.objects[key]

    async def download_to_path(self, key: str, destination: object) -> StoredObject:
        raise AssertionError("download_to_path should not be called from ReplayService")

    async def upload_from_path(self, key: str, source: object) -> StoredObject:
        raise AssertionError("upload_from_path should not be called from ReplayService")

    def iter_range(self, key: str, start: int, end: int) -> object:
        raise AssertionError("iter_range should not be called from ReplayService")

    async def delete(self, key: str) -> None:
        raise AssertionError("delete should not be called from ReplayService")


def _service(
    *,
    match_repo: FakeMatchRepository | None = None,
    replay_repo: FakeReplayRepository | None = None,
    job_repo: FakeReplayJobRepository | None = None,
    artifact_repo: FakeReplayArtifactRepository | None = None,
    storage: FakeReplayStorage | None = None,
    settings: Settings | None = None,
) -> tuple[
    ReplayService,
    FakeMatchRepository,
    FakeReplayRepository,
    FakeReplayJobRepository,
    FakeReplayArtifactRepository,
    FakeReplayStorage,
]:
    match_repository = match_repo or FakeMatchRepository(snapshot=_snapshot())
    replay_repository = replay_repo or FakeReplayRepository()
    job_repository = job_repo or FakeReplayJobRepository()
    artifact_repository = artifact_repo or FakeReplayArtifactRepository()
    replay_storage = storage or FakeReplayStorage()
    service = ReplayService(
        settings=settings or _settings(),
        match_repository=match_repository,
        replay_repository=replay_repository,
        job_repository=job_repository,
        artifact_repository=artifact_repository,
        storage=replay_storage,
    )
    return (
        service,
        match_repository,
        replay_repository,
        job_repository,
        artifact_repository,
        replay_storage,
    )


async def _seed_replay(
    replay_repo: FakeReplayRepository,
    *,
    status: ReplayStatus = ReplayStatus.CREATED,
    **overrides: object,
) -> tuple[ReplayUploadRow, str]:
    access_token, digest = issue_replay_token(SECRET)
    values: dict[str, object] = {
        "id": uuid4(),
        "match_id": "NA1_1234567890",
        "platform": Platform.NA1.value,
        "selected_puuid": "selected-player-puuid",
        "match_duration_ms": 1_800_000,
        "status": status.value,
        "progress_percent": 0,
        "token_digest": digest,
        "original_filename": "recording.mp4",
        "declared_content_type": "video/mp4",
        "declared_size_bytes": 1_000_000,
        "game_time_zero_ms": 48231,
        "source_object_key": "source/abc/input",
        "rights_statement_version": "2026-08-01",
        "rights_attested_at": NOW,
        "upload_expires_at": NOW + timedelta(minutes=30),
        "source_delete_after": NOW + timedelta(hours=24),
        "warning_codes": [],
        "created_at": NOW,
        "updated_at": NOW,
        "version": 1,
    }
    values.update(overrides)
    row = ReplayUploadRow(**values)
    await replay_repo.create(row)
    return row, access_token


@pytest.mark.asyncio
async def test_create_fails_when_replay_disabled() -> None:
    service, *_ = _service(settings=_settings(replay_enabled=False, replay_token_secret="x" * 32))
    with pytest.raises(ApiError) as raised:
        await service.create(_create_request(), now=NOW)
    assert raised.value.code == "REPLAY_DISABLED"
    assert raised.value.status_code in {403, 503}


@pytest.mark.asyncio
async def test_create_fails_when_match_missing() -> None:
    service, *_ = _service(match_repo=FakeMatchRepository(snapshot=None))
    with pytest.raises(ApiError) as raised:
        await service.create(_create_request(), now=NOW)
    assert raised.value.code == "REPLAY_MATCH_NOT_FOUND"
    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_create_fails_when_puuid_not_in_match() -> None:
    service, *_ = _service(match_repo=FakeMatchRepository(snapshot=_snapshot(puuid="other")))
    with pytest.raises(ApiError) as raised:
        await service.create(_create_request(), now=NOW)
    assert raised.value.code == "REPLAY_PLAYER_NOT_IN_MATCH"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"rights_attested": False},
        {"rights_statement_version": "1999-01-01"},
    ],
)
async def test_create_fails_when_rights_attestation_invalid(overrides: dict[str, object]) -> None:
    service, *_ = _service()
    with pytest.raises(ApiError) as raised:
        await service.create(_create_request(**overrides), now=NOW)
    assert raised.value.code == "REPLAY_RIGHTS_ATTESTATION_REQUIRED"


@pytest.mark.asyncio
async def test_create_fails_when_declared_size_too_large() -> None:
    service, *_ = _service()
    with pytest.raises(ApiError) as raised:
        await service.create(
            _create_request(declared_size_bytes=4 * GIB + 1),
            now=NOW,
        )
    assert raised.value.code == "REPLAY_TOO_LARGE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename,content_type",
    [
        ("recording.exe", "video/mp4"),
        ("recording.mp4", "text/plain"),
        ("recording", "video/mp4"),
    ],
)
async def test_create_fails_when_extension_or_content_type_invalid(
    filename: str, content_type: str
) -> None:
    service, *_ = _service()
    with pytest.raises(ApiError) as raised:
        await service.create(
            _create_request(original_filename=filename, declared_content_type=content_type),
            now=NOW,
        )
    assert raised.value.code == "REPLAY_UPLOAD_INVALID"


@pytest.mark.asyncio
async def test_create_success_returns_token_once_and_stores_digest() -> None:
    service, _, replay_repo, _, _, storage = _service()
    created = await service.create(_create_request(), now=NOW)

    assert created.status == ReplayStatus.CREATED
    assert created.access_token
    assert created.upload.method == "PUT"
    assert created.retention.source_hours_after_processing == 24
    assert created.retention.derived_days_after_ready == 7

    stored = await replay_repo.get(created.replay_id)
    assert stored is not None
    assert stored.token_digest != created.access_token
    assert stored.match_duration_ms == 1_800_000
    assert stored.selected_puuid == "selected-player-puuid"
    assert verify_replay_token(SECRET, created.access_token, stored.token_digest)
    assert storage.upload_targets
    assert stored.source_object_key == storage.upload_targets[0]["key"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replay_id,token",
    [
        (uuid4(), "valid-looking-token"),
        ("known", "wrong-token"),
    ],
)
async def test_missing_and_wrong_token_have_same_public_error(
    replay_id: UUID | str, token: str
) -> None:
    service, _, replay_repo, *_ = _service()
    row, valid_token = await _seed_replay(replay_repo)
    if replay_id == "known":
        target_id = row.id
        bearer = "wrong-token"
    else:
        target_id = replay_id
        bearer = valid_token if token == "valid-looking-token" else token

    with pytest.raises(ApiError) as raised:
        await service.get_status(target_id, bearer)
    assert raised.value.status_code == 404
    assert raised.value.code == "REPLAY_NOT_FOUND"


@pytest.mark.asyncio
async def test_complete_enqueues_once_and_is_idempotent_from_queued() -> None:
    service, _, replay_repo, job_repo, _, storage = _service()
    row, token = await _seed_replay(replay_repo, status=ReplayStatus.UPLOADED)
    assert row.source_object_key is not None
    storage.objects[row.source_object_key] = StoredObject(
        key=row.source_object_key, size_bytes=1_000_000, sha256="a" * 64
    )

    first = await service.complete(row.id, token, now=NOW)
    assert first.status == ReplayStatus.QUEUED
    assert len(job_repo.jobs) == 1
    assert job_repo.jobs[0].kind == ReplayJobKind.PROCESS.value

    second = await service.complete(row.id, token, now=NOW)
    assert second.status == ReplayStatus.QUEUED
    assert len(job_repo.jobs) == 1


@pytest.mark.asyncio
async def test_complete_from_created_transitions_through_uploaded() -> None:
    service, _, replay_repo, job_repo, _, storage = _service()
    row, token = await _seed_replay(replay_repo, status=ReplayStatus.CREATED)
    assert row.source_object_key is not None
    storage.objects[row.source_object_key] = StoredObject(
        key=row.source_object_key, size_bytes=1_000_000, sha256="a" * 64
    )

    result = await service.complete(row.id, token, now=NOW)
    assert result.status == ReplayStatus.QUEUED
    assert len(job_repo.jobs) == 1
    stored = await replay_repo.get(row.id)
    assert stored is not None
    assert stored.actual_size_bytes == 1_000_000


@pytest.mark.asyncio
async def test_retry_requires_failed_retryable_source() -> None:
    service, _, replay_repo, job_repo, _, storage = _service()
    row, token = await _seed_replay(
        replay_repo,
        status=ReplayStatus.FAILED,
        error_code="REPLAY_PROCESSING_FAILED",
        error_retryable=True,
        source_delete_after=NOW + timedelta(hours=1),
    )
    assert row.source_object_key is not None
    storage.objects[row.source_object_key] = StoredObject(
        key=row.source_object_key, size_bytes=1_000_000, sha256="a" * 64
    )

    result = await service.retry(row.id, token, now=NOW)
    assert result.status == ReplayStatus.QUEUED
    assert len(job_repo.jobs) == 1

    # non-retryable
    row2, token2 = await _seed_replay(
        replay_repo,
        status=ReplayStatus.FAILED,
        error_code="REPLAY_MEDIA_UNSUPPORTED",
        error_retryable=False,
        source_delete_after=NOW + timedelta(hours=1),
    )
    storage.objects[row2.source_object_key or ""] = StoredObject(
        key=row2.source_object_key or "x", size_bytes=1, sha256="b" * 64
    )
    with pytest.raises(ApiError) as raised:
        await service.retry(row2.id, token2, now=NOW)
    assert raised.value.code == "REPLAY_RETRY_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_retry_rejects_when_source_retention_elapsed_or_missing() -> None:
    service, _, replay_repo, _, _, storage = _service()
    row, token = await _seed_replay(
        replay_repo,
        status=ReplayStatus.FAILED,
        error_retryable=True,
        source_delete_after=NOW - timedelta(seconds=1),
    )
    with pytest.raises(ApiError) as raised:
        await service.retry(row.id, token, now=NOW)
    assert raised.value.code == "REPLAY_RETRY_NOT_ALLOWED"

    row2, token2 = await _seed_replay(
        replay_repo,
        status=ReplayStatus.FAILED,
        error_retryable=True,
        source_delete_after=NOW + timedelta(hours=1),
    )
    with pytest.raises(ApiError) as raised:
        await service.retry(row2.id, token2, now=NOW)
    assert raised.value.code == "REPLAY_RETRY_NOT_ALLOWED"
    assert storage.objects == {}


@pytest.mark.asyncio
async def test_request_delete_transitions_to_deleting_and_enqueues_cleanup() -> None:
    service, _, replay_repo, job_repo, *_ = _service()
    row, token = await _seed_replay(replay_repo, status=ReplayStatus.READY)

    result = await service.request_delete(row.id, token, now=NOW)
    assert result.status == ReplayStatus.DELETING
    assert len(job_repo.jobs) == 1
    assert job_repo.jobs[0].kind == ReplayJobKind.DELETE_ALL.value

    again = await service.request_delete(row.id, token, now=NOW)
    assert again.status == ReplayStatus.DELETING
    assert len(job_repo.jobs) == 1


@pytest.mark.asyncio
async def test_mark_local_uploaded_transitions_created_to_uploaded() -> None:
    service, _, replay_repo, *_ = _service()
    row, token = await _seed_replay(replay_repo, status=ReplayStatus.CREATED)

    result = await service.mark_local_uploaded(row.id, token, actual_size_bytes=999, now=NOW)
    assert result.status == ReplayStatus.UPLOADED
    stored = await replay_repo.get(row.id)
    assert stored is not None
    assert stored.actual_size_bytes == 999


@pytest.mark.asyncio
async def test_list_artifacts_returns_public_access_objects() -> None:
    service, _, replay_repo, _, artifact_repo, _ = _service()
    row, token = await _seed_replay(replay_repo, status=ReplayStatus.READY)
    artifact_repo.rows.append(
        ReplayArtifactRow(
            id=uuid4(),
            replay_id=row.id,
            kind=ReplayArtifactKind.ANCHOR_FRAME.value,
            game_time_ms=0,
            video_time_ms=48231,
            object_key="frames/abc/anchor",
            sha256="c" * 64,
            media_type="image/jpeg",
            size_bytes=100,
            width=1280,
            height=720,
            duration_ms=None,
            created_at=NOW,
            delete_after=NOW + timedelta(days=7),
        )
    )

    artifacts = await service.list_artifacts(row.id, token, now=NOW)
    assert len(artifacts) == 1
    assert artifacts[0].kind == ReplayArtifactKind.ANCHOR_FRAME
    assert artifacts[0].access.mode == "bearer"
    assert "object_key" not in artifacts[0].model_dump()
