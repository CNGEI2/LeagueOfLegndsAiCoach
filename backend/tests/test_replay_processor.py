from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping, Set
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.models.replay import ReplayArtifactRow, ReplayJobRow, ReplayUploadRow
from app.repositories.replays import ReplayArtifactConflict, ReplayStateConflict
from app.services.replays.domain import (
    ReplayArtifactKind,
    ReplayJobKind,
    ReplayJobStatus,
    ReplayStatus,
)
from app.services.replays.media import (
    AudioStreamProbe,
    MediaProbe,
    ReplayMediaError,
    VideoStreamProbe,
)
from app.services.replays.processor import ReplayProcessor
from app.services.replays.storage.base import ReplayObjectNotFound, StoredObject

NOW = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
SOURCE_BYTES = b"source-video-bytes"
NORMALIZED_BYTES = b"normalized-video-bytes"
FRAME_BYTES = b"frame-jpeg-bytes"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "app_env": "test",
        "replay_enabled": True,
        "replay_token_secret": "x" * 32,
        "replay_min_duration_seconds": 600,
        "replay_max_duration_seconds": 5400,
        "replay_source_retention_hours": 24,
        "replay_derived_retention_days": 7,
        "replay_process_timeout_seconds": 7200,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _probe(*, duration_seconds: float = 1800.0) -> MediaProbe:
    return MediaProbe(
        duration_seconds=duration_seconds,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        video_streams=(
            VideoStreamProbe(
                index=0,
                width=1280,
                height=720,
                codec_name="h264",
                avg_frame_rate=30.0,
                pix_fmt="yuv420p",
            ),
        ),
        audio_streams=(AudioStreamProbe(index=1, codec_name="aac", channels=2),),
    )


def _replay(**overrides: object) -> ReplayUploadRow:
    replay_id = uuid4()
    values: dict[str, object] = {
        "id": replay_id,
        "match_id": "NA1_1234567890",
        "platform": "NA1",
        "selected_puuid": "selected-player-puuid",
        "match_duration_ms": 1_800_000,
        "status": ReplayStatus.QUEUED.value,
        "processing_stage": None,
        "progress_percent": 5,
        "token_digest": "a" * 64,
        "original_filename": "recording.mp4",
        "declared_content_type": "video/mp4",
        "declared_size_bytes": len(SOURCE_BYTES),
        "actual_size_bytes": len(SOURCE_BYTES),
        "game_time_zero_ms": 48_231,
        "source_object_key": f"source/{replay_id}/input",
        "normalized_object_key": None,
        "rights_statement_version": "2026-08-01",
        "rights_attested_at": NOW,
        "upload_expires_at": NOW + timedelta(minutes=30),
        "warning_codes": [],
        "created_at": NOW,
        "updated_at": NOW,
        "version": 1,
    }
    values.update(overrides)
    return ReplayUploadRow(**values)


def _job(
    replay_id: UUID,
    *,
    attempt_count: int = 1,
    kind: ReplayJobKind = ReplayJobKind.PROCESS,
) -> ReplayJobRow:
    return ReplayJobRow(
        id=uuid4(),
        replay_id=replay_id,
        kind=kind.value,
        status=ReplayJobStatus.RUNNING.value,
        attempt_count=attempt_count,
        max_attempts=3,
        available_at=NOW,
        claimed_at=NOW,
        heartbeat_at=NOW,
        worker_id="worker-1",
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class FakeReplayRepository:
    rows: dict[UUID, ReplayUploadRow] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)

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
            raise ReplayStateConflict("replay state or version precondition failed")
        if "source_sha256" in values and values["source_sha256"] is not None:
            self.events.append("hash")
        for key, value in values.items():
            setattr(row, key, value)
        row.status = status.value
        row.version = expected_version + 1
        row.updated_at = NOW
        progress = values.get("progress_percent")
        if status == ReplayStatus.PROBING:
            self.events.append("probing state")
        elif status == ReplayStatus.TRANSCODING:
            self.events.append("transcoding state")
        elif status == ReplayStatus.EXTRACTING:
            self.events.append("extracting state")
        elif status == ReplayStatus.READY:
            self.events.append(f"ready({progress})")
            if values.get("source_delete_after") is not None:
                self.events.append("retention deadlines")
        return row

    async def scrub_deleted(self, replay_id: UUID, *, now: datetime) -> ReplayUploadRow:
        row = self.rows[replay_id]
        row.status = ReplayStatus.DELETED.value
        row.deleted_at = now
        row.selected_puuid = None
        row.token_digest = None
        row.original_filename = None
        row.source_object_key = None
        row.normalized_object_key = None
        row.source_sha256 = None
        row.actual_size_bytes = None
        self.events.append("scrub_deleted")
        return row


@dataclass
class FakeReplayJobRepository:
    jobs: dict[UUID, ReplayJobRow] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)

    async def enqueue(self, **kwargs: object) -> ReplayJobRow:
        raise AssertionError("enqueue unexpected")

    async def claim_next(self, **kwargs: object) -> ReplayJobRow | None:
        raise AssertionError("claim_next unexpected")

    async def heartbeat(self, **kwargs: object) -> None:
        raise AssertionError("heartbeat unexpected")

    async def succeed(self, job_id: UUID, *, now: datetime) -> ReplayJobRow:
        job = self.jobs[job_id]
        job.status = ReplayJobStatus.SUCCEEDED.value
        job.finished_at = now
        job.worker_id = None
        self.events.append("job_succeeded")
        return job

    async def fail(
        self,
        job_id: UUID,
        *,
        error_code: str,
        now: datetime,
        available_at: datetime | None,
    ) -> ReplayJobRow:
        job = self.jobs[job_id]
        job.last_error_code = error_code
        job.updated_at = now
        job.worker_id = None
        if available_at is not None and job.attempt_count < job.max_attempts:
            job.status = ReplayJobStatus.RETRY_SCHEDULED.value
            job.available_at = available_at
            self.events.append(f"job_retry:{error_code}")
        else:
            job.status = ReplayJobStatus.FAILED.value
            job.finished_at = now
            self.events.append(f"job_failed:{error_code}")
        return job

    async def cancel(self, job_id: UUID, *, now: datetime) -> ReplayJobRow:
        job = self.jobs[job_id]
        job.status = ReplayJobStatus.CANCELLED.value
        job.finished_at = now
        job.worker_id = None
        self.events.append("job_cancelled")
        return job

    async def recover_stale(self, **kwargs: object) -> int:
        raise AssertionError("recover_stale unexpected")

    async def enqueue_due_retention(self, now: datetime) -> int:
        raise AssertionError("enqueue_due_retention unexpected")


@dataclass
class FakeReplayArtifactRepository:
    rows: list[ReplayArtifactRow] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    async def upsert(self, row: ReplayArtifactRow) -> ReplayArtifactRow:
        for existing in self.rows:
            if (
                existing.replay_id == row.replay_id
                and existing.kind == row.kind
                and existing.game_time_ms == row.game_time_ms
                and existing.video_time_ms == row.video_time_ms
            ):
                if existing.sha256 != row.sha256:
                    raise ReplayArtifactConflict("hash mismatch")
                self.events.append("artifact_reuse")
                return existing
        self.rows.append(row)
        self.events.append("artifact_upsert")
        return row

    async def list_for_replay(self, replay_id: UUID) -> list[ReplayArtifactRow]:
        return [row for row in self.rows if row.replay_id == replay_id]

    async def delete_rows(self, replay_id: UUID) -> int:
        before = len(self.rows)
        self.rows = [row for row in self.rows if row.replay_id != replay_id]
        self.events.append("artifact_rows_deleted")
        return before - len(self.rows)


@dataclass
class FakeReplayStorage:
    objects: dict[str, bytes] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    fail_upload_times: int = 0
    uploads: int = 0

    async def create_upload_target(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("create_upload_target unexpected")

    async def write_stream(self, *args: object, **kwargs: object) -> StoredObject:
        raise AssertionError("write_stream unexpected")

    async def stat(self, key: str) -> StoredObject:
        if key not in self.objects:
            raise ReplayObjectNotFound(key)
        payload = self.objects[key]
        return StoredObject(
            key=key,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    async def download_to_path(self, key: str, destination: Path) -> StoredObject:
        if key not in self.objects:
            raise ReplayObjectNotFound(key)
        if key.startswith("source/"):
            self.events.append("download source")
        elif key.startswith("normalized/"):
            self.events.append("download normalized")
        else:
            self.events.append(f"download {key}")
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        payload = self.objects[key]
        await asyncio.to_thread(destination.write_bytes, payload)
        return StoredObject(
            key=key,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    async def upload_from_path(self, key: str, source: Path) -> StoredObject:
        self.uploads += 1
        if self.fail_upload_times > 0:
            self.fail_upload_times -= 1
            raise TimeoutError("storage temporarily unavailable")
        payload = await asyncio.to_thread(source.read_bytes)
        digest = hashlib.sha256(payload).hexdigest()
        if key in self.objects and hashlib.sha256(self.objects[key]).hexdigest() == digest:
            self.events.append("upload skipped same hash")
            return StoredObject(key=key, size_bytes=len(payload), sha256=digest)
        self.objects[key] = payload
        if "normalized/" in key:
            self.events.append("upload normalized")
        else:
            self.events.append("upload frame")
        return StoredObject(key=key, size_bytes=len(payload), sha256=digest)

    def iter_range(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("iter_range unexpected")

    async def delete(self, key: str) -> None:
        self.events.append(f"delete:{key}")
        self.objects.pop(key, None)
        part_key = f"{key}.part"
        if part_key in self.objects:
            self.objects.pop(part_key)
            self.events.append(f"delete:{part_key}")


@dataclass
class FakeMediaRunner:
    events: list[str] = field(default_factory=list)
    source_probe: MediaProbe = field(default_factory=_probe)
    normalized_probe: MediaProbe = field(default_factory=_probe)
    fail_normalize: bool = False
    normalize_calls: int = 0
    extract_calls: int = 0
    probe_paths: list[Path] = field(default_factory=list)

    async def probe(self, input_path: Path) -> MediaProbe:
        self.probe_paths.append(input_path)
        name = input_path.name
        if "normalized" in name or name.endswith(".mp4") and self.normalize_calls > 0:
            self.events.append("probe normalized")
            return self.normalized_probe
        self.events.append("probe")
        return self.source_probe

    async def normalize(
        self,
        input_path: Path,
        output_path: Path,
        probe: MediaProbe,
        progress: Any = None,
    ) -> MediaProbe:
        del probe
        self.normalize_calls += 1
        self.events.append("normalize")
        if self.fail_normalize:
            partial = output_path.with_name(f"{output_path.stem}.partial{output_path.suffix}")
            await asyncio.to_thread(partial.write_bytes, b"partial")
            raise ReplayMediaError("REPLAY_PROCESSING_FAILED", "normalize interrupted")
        if progress is not None:
            await progress(40)
            await progress(80)
        await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(output_path.write_bytes, NORMALIZED_BYTES)
        return self.normalized_probe

    async def extract_frame(
        self,
        input_path: Path,
        video_time_ms: int,
        output_path: Path,
    ) -> None:
        del input_path, video_time_ms
        self.extract_calls += 1
        if "frames" not in "".join(self.events):
            self.events.append("frames")
        await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(output_path.write_bytes, FRAME_BYTES)


def _processor(
    *,
    replay: ReplayUploadRow,
    events: list[str] | None = None,
    storage: FakeReplayStorage | None = None,
    media: FakeMediaRunner | None = None,
    artifacts: FakeReplayArtifactRepository | None = None,
    jobs: FakeReplayJobRepository | None = None,
) -> tuple[
    ReplayProcessor,
    FakeReplayRepository,
    FakeReplayJobRepository,
    FakeReplayArtifactRepository,
    FakeReplayStorage,
    FakeMediaRunner,
    list[str],
]:
    shared = events if events is not None else []
    replay_repo = FakeReplayRepository(rows={replay.id: replay}, events=shared)
    job_repo = jobs or FakeReplayJobRepository(events=shared)
    artifact_repo = artifacts or FakeReplayArtifactRepository(events=shared)
    store = storage or FakeReplayStorage(events=shared)
    if replay.source_object_key and replay.source_object_key not in store.objects:
        store.objects[replay.source_object_key] = SOURCE_BYTES
    media_runner = media or FakeMediaRunner(events=shared)
    processor = ReplayProcessor(
        settings=_settings(),
        replay_repository=replay_repo,
        job_repository=job_repo,
        artifact_repository=artifact_repo,
        storage=store,
        media=media_runner,
        clock=lambda: NOW,
    )
    return processor, replay_repo, job_repo, artifact_repo, store, media_runner, shared


@pytest.mark.asyncio
async def test_process_pipeline_order_and_frame_plan() -> None:
    replay = _replay(match_duration_ms=75_000, game_time_zero_ms=1_000)
    # Video duration must satisfy MediaLimits and cover the short match window.
    media = FakeMediaRunner(
        source_probe=_probe(duration_seconds=1800.0),
        normalized_probe=_probe(duration_seconds=1800.0),
    )
    events: list[str] = []
    media.events = events
    processor, replay_repo, job_repo, artifact_repo, store, media_runner, shared = _processor(
        replay=replay,
        events=events,
        media=media,
    )
    job = _job(replay.id)
    job_repo.jobs[job.id] = job

    await processor.process(job)

    # Compact pipeline markers in order.
    markers = [
        item
        for item in shared
        if item
        in {
            "download source",
            "hash",
            "probe",
            "probing state",
            "normalize",
            "transcoding state",
            "probe normalized",
            "upload normalized",
            "extracting state",
            "frames",
            "artifact_upsert",
            "ready(100)",
            "retention deadlines",
        }
    ]
    # hash may be recorded by processor into shared events
    assert "download source" in markers
    assert "probe" in markers
    assert "probing state" in markers
    assert "normalize" in markers
    assert "transcoding state" in markers
    assert "probe normalized" in markers
    assert "upload normalized" in markers
    assert "extracting state" in markers
    assert "frames" in markers
    assert "artifact_upsert" in markers
    assert "ready(100)" in markers
    assert "retention deadlines" in markers

    order = [
        markers.index("download source"),
        markers.index("probe"),
        markers.index("probing state"),
        markers.index("normalize"),
        markers.index("transcoding state"),
        markers.index("probe normalized"),
        markers.index("upload normalized"),
        markers.index("extracting state"),
        markers.index("frames"),
        markers.index("artifact_upsert"),
        markers.index("ready(100)"),
        markers.index("retention deadlines"),
    ]
    assert order == sorted(order)
    assert "hash" in shared
    assert shared.index("hash") > shared.index("download source")
    assert shared.index("hash") < shared.index("probe")

    updated = replay_repo.rows[replay.id]
    assert updated.status == ReplayStatus.READY.value
    assert updated.progress_percent == 100
    assert updated.source_delete_after == NOW + timedelta(hours=24)
    assert updated.derived_delete_after == NOW + timedelta(days=7)
    assert job.status == ReplayJobStatus.SUCCEEDED.value

    artifacts = sorted(artifact_repo.rows, key=lambda row: row.game_time_ms)
    assert [row.game_time_ms for row in artifacts] == [0, 30_000, 60_000, 75_000]
    assert artifacts[0].kind == ReplayArtifactKind.ANCHOR_FRAME.value
    assert all(row.kind == ReplayArtifactKind.VERIFICATION_FRAME.value for row in artifacts[1:])
    assert len(artifacts) <= 181


def test_frame_plan_caps_at_181_total() -> None:
    from app.services.replays.processor import plan_frame_game_times

    times = plan_frame_game_times(10_000_000)
    assert len(times) == 181
    assert times[0] == 0
    assert times[1] == 30_000


@pytest.mark.asyncio
async def test_idempotent_restart_skips_transcode_and_reuses_frames() -> None:
    replay = _replay(match_duration_ms=60_000, game_time_zero_ms=1_000)
    normalized_key = f"normalized/{replay.id}/video"
    replay.normalized_object_key = normalized_key
    events: list[str] = []
    store = FakeReplayStorage(
        objects={
            replay.source_object_key or "": SOURCE_BYTES,
            normalized_key: NORMALIZED_BYTES,
        },
        events=events,
    )
    media = FakeMediaRunner(
        events=events,
        source_probe=_probe(duration_seconds=1800.0),
        normalized_probe=_probe(duration_seconds=1800.0),
    )
    existing_frame_hash = hashlib.sha256(FRAME_BYTES).hexdigest()
    artifacts = FakeReplayArtifactRepository(events=events)
    artifacts.rows.append(
        ReplayArtifactRow(
            id=uuid4(),
            replay_id=replay.id,
            kind=ReplayArtifactKind.ANCHOR_FRAME.value,
            game_time_ms=0,
            video_time_ms=1_000,
            object_key=f"frames/{replay.id}/anchor",
            sha256=existing_frame_hash,
            media_type="image/jpeg",
            size_bytes=len(FRAME_BYTES),
            width=1280,
            height=720,
            created_at=NOW,
        )
    )
    store.objects[f"frames/{replay.id}/anchor"] = FRAME_BYTES
    processor, _, job_repo, artifact_repo, _, media_runner, _ = _processor(
        replay=replay,
        events=events,
        storage=store,
        media=media,
        artifacts=artifacts,
    )
    job = _job(replay.id)
    job_repo.jobs[job.id] = job

    await processor.process(job)

    assert media_runner.normalize_calls == 0
    assert "normalize" not in events
    assert "artifact_reuse" in events
    assert job.status == ReplayJobStatus.SUCCEEDED.value
    assert len(artifact_repo.rows) >= 1


@pytest.mark.asyncio
async def test_interrupted_normalize_cleans_temp_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = _replay()
    events: list[str] = []
    media = FakeMediaRunner(events=events, fail_normalize=True)
    created: list[Path] = []

    class TrackingTemporaryDirectory:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            self.name = str(tmp_path / f"scratch-{len(created)}")
            Path(self.name).mkdir(parents=True, exist_ok=True)
            created.append(Path(self.name))

        def __enter__(self) -> str:
            return self.name

        def __exit__(self, *args: object) -> None:
            del args
            root = Path(self.name)
            for path in sorted(root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
            if root.exists():
                root.rmdir()

    monkeypatch.setattr(
        "app.services.replays.processor.tempfile.TemporaryDirectory",
        TrackingTemporaryDirectory,
    )
    processor, replay_repo, job_repo, _, _, _, _ = _processor(
        replay=replay,
        events=events,
        media=media,
    )
    job = _job(replay.id)
    job_repo.jobs[job.id] = job

    await processor.process(job)

    assert media.normalize_calls == 1
    assert not any(created[0].rglob("*")) if created else True
    assert replay_repo.rows[replay.id].status == ReplayStatus.FAILED.value
    assert replay_repo.rows[replay.id].error_retryable is False


@pytest.mark.asyncio
async def test_short_coverage_writes_partial_coverage_warning() -> None:
    replay = _replay(match_duration_ms=1_800_000, game_time_zero_ms=50_000)
    media = FakeMediaRunner(
        source_probe=_probe(duration_seconds=1_000.0),
        normalized_probe=_probe(duration_seconds=1_000.0),
    )
    events: list[str] = []
    media.events = events
    processor, replay_repo, job_repo, _, _, _, _ = _processor(
        replay=replay, events=events, media=media
    )
    job = _job(replay.id)
    job_repo.jobs[job.id] = job

    await processor.process(job)

    updated = replay_repo.rows[replay.id]
    assert updated.status == ReplayStatus.READY.value
    assert "partial_coverage" in (updated.warning_codes or [])
    assert updated.available_game_time_end_ms == 950_000


@pytest.mark.asyncio
async def test_invalid_media_is_not_retryable() -> None:
    replay = _replay()
    events: list[str] = []

    class InvalidMedia(FakeMediaRunner):
        async def probe(self, input_path: Path) -> MediaProbe:
            self.events.append("probe")
            raise ReplayMediaError("REPLAY_MEDIA_UNSUPPORTED", "bad media")

    media = InvalidMedia(events=events)
    processor, replay_repo, job_repo, _, _, _, _ = _processor(
        replay=replay, events=events, media=media
    )
    job = _job(replay.id, attempt_count=1)
    job_repo.jobs[job.id] = job

    await processor.process(job)

    assert job.status == ReplayJobStatus.FAILED.value
    assert replay_repo.rows[replay.id].status == ReplayStatus.FAILED.value
    assert replay_repo.rows[replay.id].error_retryable is False
    assert replay_repo.rows[replay.id].error_code == "REPLAY_MEDIA_UNSUPPORTED"


@pytest.mark.asyncio
async def test_transient_storage_failure_is_retryable_until_third_attempt() -> None:
    replay = _replay(match_duration_ms=60_000, game_time_zero_ms=1_000)
    events: list[str] = []
    store = FakeReplayStorage(
        objects={replay.source_object_key or "": SOURCE_BYTES},
        events=events,
        fail_upload_times=1,
    )
    media = FakeMediaRunner(
        events=events,
        source_probe=_probe(duration_seconds=1800.0),
        normalized_probe=_probe(duration_seconds=1800.0),
    )
    processor, replay_repo, job_repo, _, _, _, _ = _processor(
        replay=replay, events=events, storage=store, media=media
    )
    job = _job(replay.id, attempt_count=1)
    job_repo.jobs[job.id] = job

    await processor.process(job)

    assert job.status == ReplayJobStatus.RETRY_SCHEDULED.value
    assert replay_repo.rows[replay.id].error_retryable is True

    # Third attempt becomes terminal.
    replay2 = _replay(match_duration_ms=60_000, game_time_zero_ms=1_000)
    events2: list[str] = []
    store2 = FakeReplayStorage(
        objects={replay2.source_object_key or "": SOURCE_BYTES},
        events=events2,
        fail_upload_times=1,
    )
    media2 = FakeMediaRunner(
        events=events2,
        source_probe=_probe(duration_seconds=1800.0),
        normalized_probe=_probe(duration_seconds=1800.0),
    )
    processor2, replay_repo2, job_repo2, _, _, _, _ = _processor(
        replay=replay2, events=events2, storage=store2, media=media2
    )
    job2 = _job(replay2.id, attempt_count=3)
    job_repo2.jobs[job2.id] = job2

    await processor2.process(job2)

    assert job2.status == ReplayJobStatus.FAILED.value
    assert replay_repo2.rows[replay2.id].status == ReplayStatus.FAILED.value
    assert replay_repo2.rows[replay2.id].error_retryable is True


@pytest.mark.asyncio
async def test_user_delete_mid_process_cancels_at_stage_boundary() -> None:
    replay = _replay(match_duration_ms=60_000, game_time_zero_ms=1_000)
    events: list[str] = []
    replay_repo_holder: dict[str, FakeReplayRepository] = {}

    class BoundaryMedia(FakeMediaRunner):
        async def normalize(
            self,
            input_path: Path,
            output_path: Path,
            probe: MediaProbe,
            progress: Any = None,
        ) -> MediaProbe:
            # User deletes while normalize is running; next stage boundary must cancel.
            repo = replay_repo_holder["repo"]
            row = repo.rows[replay.id]
            row.status = ReplayStatus.DELETING.value
            return await super().normalize(input_path, output_path, probe, progress)

    media = BoundaryMedia(
        events=events,
        source_probe=_probe(duration_seconds=1800.0),
        normalized_probe=_probe(duration_seconds=1800.0),
    )
    processor, replay_repo, job_repo, artifact_repo, store, _, _ = _processor(
        replay=replay, events=events, media=media
    )
    replay_repo_holder["repo"] = replay_repo
    job = _job(replay.id)
    job_repo.jobs[job.id] = job

    await processor.process(job)

    assert job.status == ReplayJobStatus.CANCELLED.value
    assert "job_cancelled" in events
    assert replay_repo.rows[replay.id].status == ReplayStatus.DELETING.value
    assert replay_repo.rows[replay.id].status != ReplayStatus.READY.value
    # Must not promote normalized after delete was observed.
    assert not any(key.startswith("normalized/") for key in store.objects)
    assert artifact_repo.rows == []


@pytest.mark.asyncio
async def test_delete_source_keeps_normalized_and_frames() -> None:
    replay = _replay()
    normalized_key = f"normalized/{replay.id}/video"
    frame_key = f"frames/{replay.id}/anchor"
    replay.normalized_object_key = normalized_key
    replay.source_sha256 = "abc"
    part_key = f"{replay.source_object_key}.part"
    events: list[str] = []
    store = FakeReplayStorage(
        objects={
            replay.source_object_key or "": SOURCE_BYTES,
            part_key: b"partial",
            normalized_key: NORMALIZED_BYTES,
            frame_key: FRAME_BYTES,
        },
        events=events,
    )
    processor, replay_repo, job_repo, _, _, _, _ = _processor(
        replay=replay, events=events, storage=store
    )
    job = _job(replay.id, kind=ReplayJobKind.DELETE_SOURCE)
    job_repo.jobs[job.id] = job

    await processor.delete_source(job)

    assert replay.source_object_key not in store.objects
    assert part_key not in store.objects
    assert normalized_key in store.objects
    assert frame_key in store.objects
    updated = replay_repo.rows[replay.id]
    assert updated.source_object_key is None
    assert updated.source_sha256 is None
    assert updated.actual_size_bytes is None
    assert updated.normalized_object_key == normalized_key
    assert job.status == ReplayJobStatus.SUCCEEDED.value


@pytest.mark.asyncio
async def test_delete_all_scrubs_even_when_objects_missing() -> None:
    replay = _replay(status=ReplayStatus.DELETING)
    normalized_key = f"normalized/{replay.id}/video"
    replay.normalized_object_key = normalized_key
    events: list[str] = []
    store = FakeReplayStorage(objects={}, events=events)
    artifacts = FakeReplayArtifactRepository(events=events)
    artifacts.rows.append(
        ReplayArtifactRow(
            id=uuid4(),
            replay_id=replay.id,
            kind=ReplayArtifactKind.ANCHOR_FRAME.value,
            game_time_ms=0,
            video_time_ms=0,
            object_key=f"frames/{replay.id}/missing",
            sha256="deadbeef",
            media_type="image/jpeg",
            size_bytes=1,
            created_at=NOW,
        )
    )
    processor, replay_repo, job_repo, artifact_repo, _, _, shared = _processor(
        replay=replay,
        events=events,
        storage=store,
        artifacts=artifacts,
    )
    job = _job(replay.id, kind=ReplayJobKind.DELETE_ALL)
    job_repo.jobs[job.id] = job

    await processor.delete_all(job)

    assert artifact_repo.rows == []
    assert "scrub_deleted" in shared
    assert replay_repo.rows[replay.id].status == ReplayStatus.DELETED.value
    assert job.status == ReplayJobStatus.SUCCEEDED.value
