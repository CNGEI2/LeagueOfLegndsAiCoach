from __future__ import annotations

import asyncio
import hashlib
import random
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.metrics import MetricsRegistry
from app.core.metrics import metrics as default_metrics
from app.models.replay import ReplayArtifactRow, ReplayJobRow, ReplayUploadRow
from app.repositories.replays import (
    ReplayArtifactRepository,
    ReplayJobRepository,
    ReplayRepository,
    ReplayStateConflict,
)
from app.services.replays.domain import (
    ReplayArtifactKind,
    ReplayJobStatus,
    ReplayStatus,
    calculate_coverage,
    game_to_video_time,
)
from app.services.replays.media import (
    MediaLimits,
    ReplayMediaError,
    ReplayMediaRunner,
    validate_probe,
)
from app.services.replays.storage.base import (
    ReplayObjectNotFound,
    ReplayStorage,
    StoredObject,
    temp_upload_key,
)

_FRAME_INTERVAL_MS = 30_000
_MAX_FRAMES = 181
# FFmpeg input seeks to the exact media duration often yield no packets
# (especially for short lavfi/CFR fixtures). Keep terminal samples inside
# the decodable window by this margin.
_FRAME_SEEK_SAFE_MARGIN_MS = 100
_NON_RETRYABLE_MEDIA_CODES = frozenset(
    {
        "REPLAY_MEDIA_UNSUPPORTED",
        "REPLAY_DURATION_UNSUPPORTED",
        "REPLAY_PROCESSING_FAILED",
        "REPLAY_FFMPEG_UNAVAILABLE",
    }
)


class ReplayProcessingCancelled(Exception):
    """Replay became deleting/deleted during processing; stop without promoting outputs."""


_PROCESS_CANCEL_STATUSES = frozenset({ReplayStatus.DELETING, ReplayStatus.DELETED})


class ReplayProcessor:
    def __init__(
        self,
        *,
        settings: Settings,
        replay_repository: ReplayRepository,
        job_repository: ReplayJobRepository,
        artifact_repository: ReplayArtifactRepository,
        storage: ReplayStorage,
        media: ReplayMediaRunner,
        clock: Callable[[], datetime] | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._replays = replay_repository
        self._jobs = job_repository
        self._artifacts = artifact_repository
        self._storage = storage
        self._media = media
        self._clock = clock or (lambda: datetime.now(UTC))
        self._metrics = metrics or default_metrics

    async def process(self, job: ReplayJobRow) -> None:
        now = self._clock()
        try:
            with tempfile.TemporaryDirectory(prefix="replay-job-") as scratch:
                await self._process_in_scratch(job, Path(scratch), now=now)
        except ReplayProcessingCancelled:
            # Sweep first. Only mark CANCELLED after cleanup succeeds so a
            # failed sweep can reuse the normal PROCESS retry path.
            await self._complete_cancelled_process(job)
        except Exception as error:
            await self._handle_process_failure(job, error)
        else:
            duration = (self._clock() - now).total_seconds()
            self._metrics.replay_processing_duration_seconds.observe(
                max(0.0, duration), stage="total"
            )

    async def delete_source(self, job: ReplayJobRow) -> None:
        now = self._clock()
        try:
            row = await self._require_replay(job.replay_id)
            source_key = row.source_object_key
            source_delete_after = row.source_delete_after
            if source_key:
                await self._delete_missing_ok(source_key)
            updated = await self._replays.transition(
                replay_id=row.id,
                expected_statuses={ReplayStatus(row.status)},
                expected_version=row.version,
                status=ReplayStatus(row.status),
                values={
                    "source_object_key": None,
                    "source_sha256": None,
                    "actual_size_bytes": None,
                    "source_delete_after": None,
                    "updated_at": now,
                },
            )
            del updated
            await self._jobs.succeed(job.id, now=now)
            job.status = ReplayJobStatus.SUCCEEDED.value
            self._observe_cleanup_lag(source_delete_after, now=now, kind="source")
        except Exception as error:
            await self._fail_job(job, error=error, retryable=True, now=now)

    async def delete_all(self, job: ReplayJobRow) -> None:
        now = self._clock()
        try:
            row = await self._require_replay(job.replay_id)
            cleanup_deadline = row.derived_delete_after or row.source_delete_after
            # Confirm content is inaccessible to clients by requiring deleting/deleted.
            if ReplayStatus(row.status) not in {
                ReplayStatus.DELETING,
                ReplayStatus.DELETED,
            }:
                row = await self._replays.transition(
                    replay_id=row.id,
                    expected_statuses={ReplayStatus(row.status)},
                    expected_version=row.version,
                    status=ReplayStatus.DELETING,
                    values={"updated_at": now},
                )

            first_storage_error: Exception | None = None

            # Sweep by prefix so any orphaned object under this replay's
            # namespace is removed, even one the row/artifact rows never
            # recorded (e.g. an abandoned temp upload or a frame left behind
            # by a crashed run). This is the primary cleanup mechanism.
            for prefix in (
                f"source/{row.id}",
                f"normalized/{row.id}",
                f"frames/{row.id}",
                temp_upload_key(f"source/{row.id}"),
            ):
                try:
                    await self._storage.delete_prefix(prefix)
                except Exception as error:
                    if first_storage_error is None:
                        first_storage_error = error

            # Best-effort fallback: also delete the specific keys we know
            # about directly, in case a backend's delete_prefix doesn't cover
            # every stored representation of a key (e.g. legacy layouts).
            keys: list[str] = []
            if row.source_object_key:
                keys.append(row.source_object_key)
                if self._settings.replay_storage_backend == "s3":
                    keys.append(temp_upload_key(row.source_object_key))
            if row.normalized_object_key:
                keys.append(row.normalized_object_key)
            for artifact in await self._artifacts.list_for_replay(row.id):
                keys.append(artifact.object_key)

            for key in keys:
                try:
                    await self._delete_missing_ok(key)
                except Exception as error:
                    if first_storage_error is None:
                        first_storage_error = error
            if first_storage_error is not None:
                raise first_storage_error

            await self._artifacts.delete_rows(row.id)
            await self._replays.scrub_deleted(row.id, now=now)
            await self._jobs.succeed(job.id, now=now)
            job.status = ReplayJobStatus.SUCCEEDED.value
            self._observe_cleanup_lag(cleanup_deadline, now=now, kind="all")
        except Exception as error:
            await self._fail_job(job, error=error, retryable=True, now=now)

    async def _process_in_scratch(
        self,
        job: ReplayJobRow,
        scratch: Path,
        *,
        now: datetime,
    ) -> None:
        row = await self._require_replay(job.replay_id)
        await self._ensure_not_deleting(row)

        if not row.source_object_key:
            raise ReplayMediaError("REPLAY_MEDIA_UNSUPPORTED", "Source object is missing.")

        source_path = scratch / f"source-{uuid4().hex}.bin"
        await self._storage.download_to_path(row.source_object_key, source_path)
        source_sha256 = await _sha256_file(source_path)
        row = await self._transition(
            row,
            expected_statuses={
                ReplayStatus.QUEUED,
                ReplayStatus.PROBING,
                ReplayStatus.TRANSCODING,
                ReplayStatus.EXTRACTING,
                ReplayStatus.FAILED,
            },
            status=ReplayStatus.QUEUED
            if ReplayStatus(row.status) == ReplayStatus.QUEUED
            else ReplayStatus(row.status),
            values={
                "source_sha256": source_sha256,
                "actual_size_bytes": (await asyncio.to_thread(source_path.stat)).st_size,
                "updated_at": now,
            },
        )

        source_probe = await self._media.probe(source_path)
        row = await self._transition(
            row,
            expected_statuses={
                ReplayStatus.QUEUED,
                ReplayStatus.PROBING,
                ReplayStatus.TRANSCODING,
                ReplayStatus.EXTRACTING,
                ReplayStatus.FAILED,
            },
            status=ReplayStatus.PROBING,
            values={
                "processing_stage": "probing",
                "progress_percent": 10,
                "processing_started_at": row.processing_started_at or now,
                "updated_at": self._clock(),
            },
        )
        await self._ensure_not_deleting(row)

        limits = MediaLimits(
            min_duration_seconds=self._settings.replay_min_duration_seconds,
            max_duration_seconds=self._settings.replay_max_duration_seconds,
        )
        validated = validate_probe(source_probe, limits)
        if row.game_time_zero_ms >= int(validated.duration_seconds * 1000):
            raise ReplayMediaError(
                "REPLAY_MEDIA_UNSUPPORTED",
                "Anchor is outside the probed media duration.",
            )

        normalized_key = row.normalized_object_key or f"normalized/{row.id}/video"
        normalized_path = scratch / f"normalized-{uuid4().hex}.mp4"
        skipped_transcode = False

        if row.normalized_object_key:
            try:
                existing = await self._storage.download_to_path(
                    row.normalized_object_key, normalized_path
                )
                existing_hash = existing.sha256 or await _sha256_file(normalized_path)
                # Existing canonical object with a stable hash makes normalize idempotent.
                if existing_hash:
                    skipped_transcode = True
            except ReplayObjectNotFound:
                skipped_transcode = False

        if not skipped_transcode:

            async def _on_progress(percent: int) -> None:
                nonlocal row
                try:
                    row = await self._transition(
                        row,
                        expected_statuses={ReplayStatus.PROBING, ReplayStatus.TRANSCODING},
                        status=ReplayStatus.TRANSCODING,
                        values={
                            "processing_stage": "transcoding",
                            "progress_percent": max(15, min(80, percent)),
                            "updated_at": self._clock(),
                        },
                    )
                except ReplayProcessingCancelled:
                    raise
                except ReplayStateConflict:
                    latest = await self._require_replay(row.id)
                    await self._ensure_not_deleting(latest)
                    row = latest

            normalized_probe = await self._media.normalize(
                source_path,
                normalized_path,
                source_probe,
                progress=_on_progress,
            )
            row = await self._transition(
                row,
                expected_statuses={ReplayStatus.PROBING, ReplayStatus.TRANSCODING},
                status=ReplayStatus.TRANSCODING,
                values={
                    "processing_stage": "transcoding",
                    "progress_percent": 80,
                    "updated_at": self._clock(),
                },
            )
        else:
            normalized_probe = await self._media.probe(normalized_path)
            row = await self._transition(
                row,
                expected_statuses={
                    ReplayStatus.PROBING,
                    ReplayStatus.TRANSCODING,
                    ReplayStatus.EXTRACTING,
                    ReplayStatus.QUEUED,
                },
                status=ReplayStatus.TRANSCODING,
                values={
                    "processing_stage": "transcoding",
                    "progress_percent": 80,
                    "updated_at": self._clock(),
                },
            )

        await self._ensure_not_deleting(row)
        # Explicit normalized probe for pipeline observability / restart safety.
        if not skipped_transcode:
            normalized_probe = await self._media.probe(normalized_path)
        normalized_validated = validate_probe(
            normalized_probe,
            MediaLimits(
                min_duration_seconds=self._settings.replay_min_duration_seconds,
                max_duration_seconds=self._settings.replay_max_duration_seconds,
            ),
        )

        uploaded = await self._upload_if_not_deleting(row, normalized_key, normalized_path)
        del uploaded

        coverage = calculate_coverage(
            video_duration_ms=int(normalized_validated.duration_seconds * 1000),
            game_time_zero_ms=row.game_time_zero_ms,
            match_duration_ms=row.match_duration_ms,
        )
        warning_codes = list(row.warning_codes or [])
        if coverage.partial and "partial_coverage" not in warning_codes:
            warning_codes.append("partial_coverage")

        row = await self._transition(
            row,
            expected_statuses={ReplayStatus.TRANSCODING, ReplayStatus.EXTRACTING},
            status=ReplayStatus.EXTRACTING,
            values={
                "processing_stage": "extracting",
                "progress_percent": 81,
                "normalized_object_key": normalized_key,
                "normalized_duration_ms": int(normalized_validated.duration_seconds * 1000),
                "source_duration_ms": int(validated.duration_seconds * 1000),
                "width": normalized_validated.width,
                "height": normalized_validated.height,
                "frame_rate_numerator": 30,
                "frame_rate_denominator": 1,
                "actual_container": "mp4",
                "available_game_time_start_ms": coverage.start_ms,
                "available_game_time_end_ms": coverage.end_ms,
                "warning_codes": warning_codes,
                "updated_at": self._clock(),
            },
        )
        await self._ensure_not_deleting(row)

        duration_ms = int(normalized_validated.duration_seconds * 1000)
        extractable_end_ms = extractable_frame_end_ms(
            duration_ms=duration_ms,
            game_time_zero_ms=row.game_time_zero_ms,
        )
        frame_times = plan_frame_game_times(
            coverage.end_ms,
            extractable_end_ms=extractable_end_ms,
        )
        total = max(1, len(frame_times))
        for index, game_time_ms in enumerate(frame_times):
            await self._ensure_not_deleting(row)
            await self._upsert_frame(
                row=row,
                normalized_path=normalized_path,
                scratch=scratch,
                game_time_ms=game_time_ms,
                kind=(
                    ReplayArtifactKind.ANCHOR_FRAME
                    if game_time_ms == 0
                    else ReplayArtifactKind.VERIFICATION_FRAME
                ),
                width=normalized_validated.width,
                height=normalized_validated.height,
            )
            progress = 81 + int(((index + 1) / total) * 14)
            row = await self._transition(
                row,
                expected_statuses={ReplayStatus.EXTRACTING},
                status=ReplayStatus.EXTRACTING,
                values={
                    "processing_stage": "extracting",
                    "progress_percent": min(95, progress),
                    "updated_at": self._clock(),
                },
            )

        await self._ensure_not_deleting(row)
        finished = self._clock()
        row = await self._transition(
            row,
            expected_statuses={ReplayStatus.EXTRACTING},
            status=ReplayStatus.READY,
            values={
                "processing_stage": "ready",
                "progress_percent": 100,
                "error_code": None,
                "error_retryable": None,
                "processing_finished_at": finished,
                "source_delete_after": finished
                + timedelta(hours=self._settings.replay_source_retention_hours),
                "derived_delete_after": finished
                + timedelta(days=self._settings.replay_derived_retention_days),
                "updated_at": finished,
            },
        )
        del row
        await self._jobs.succeed(job.id, now=finished)
        job.status = ReplayJobStatus.SUCCEEDED.value

    async def _upsert_frame(
        self,
        *,
        row: ReplayUploadRow,
        normalized_path: Path,
        scratch: Path,
        game_time_ms: int,
        kind: ReplayArtifactKind,
        width: int,
        height: int,
    ) -> None:
        video_time_ms = game_to_video_time(game_time_ms, row.game_time_zero_ms)
        object_key = f"frames/{row.id}/{kind.value}-{game_time_ms}"
        existing_rows = await self._artifacts.list_for_replay(row.id)
        for existing in existing_rows:
            if (
                existing.kind == kind.value
                and existing.game_time_ms == game_time_ms
                and existing.video_time_ms == video_time_ms
            ):
                frame_path = scratch / f"frame-{uuid4().hex}.jpg"
                try:
                    await self._storage.download_to_path(existing.object_key, frame_path)
                    digest = await _sha256_file(frame_path)
                except ReplayObjectNotFound:
                    digest = None
                if digest == existing.sha256:
                    await self._artifacts.upsert(existing)
                    return
                object_key = existing.object_key
                break

        frame_path = scratch / f"frame-{uuid4().hex}.jpg"
        await self._media.extract_frame(normalized_path, video_time_ms, frame_path)
        stored = await self._upload_if_not_deleting(row, object_key, frame_path)
        artifact = ReplayArtifactRow(
            id=uuid4(),
            replay_id=row.id,
            kind=kind.value,
            game_time_ms=game_time_ms,
            video_time_ms=video_time_ms,
            object_key=object_key,
            sha256=stored.sha256 or await _sha256_file(frame_path),
            media_type="image/jpeg",
            size_bytes=stored.size_bytes,
            width=width,
            height=height,
            created_at=self._clock(),
            delete_after=None,
        )
        await self._artifacts.upsert(artifact)

    async def _handle_process_failure(self, job: ReplayJobRow, error: Exception) -> None:
        now = self._clock()
        code, retryable = classify_process_error(error)
        # Settle the worker-owned job first so the replay state reflects the
        # durable outcome: an active automatic retry is QUEUED, while only a
        # terminal job failure exposes FAILED to the manual-retry endpoint.
        await self._fail_job(job, error=error, retryable=retryable, now=now, code=code)
        replay_status = (
            ReplayStatus.QUEUED
            if job.status == ReplayJobStatus.RETRY_SCHEDULED.value
            else ReplayStatus.FAILED
        )
        try:
            row = await self._replays.get(job.replay_id)
            if row is None:
                self._metrics.replay_processing_failures_total.inc(error_code=code)
                return
            current = ReplayStatus(row.status)
            # Never pull a delete-won replay back to queued/failed.
            if current in _PROCESS_CANCEL_STATUSES:
                self._metrics.replay_processing_failures_total.inc(error_code=code)
                return
            await self._replays.transition(
                replay_id=row.id,
                expected_statuses={
                    ReplayStatus.QUEUED,
                    ReplayStatus.PROBING,
                    ReplayStatus.TRANSCODING,
                    ReplayStatus.EXTRACTING,
                    ReplayStatus.FAILED,
                },
                expected_version=row.version,
                status=replay_status,
                values={
                    "processing_stage": "queued"
                    if replay_status == ReplayStatus.QUEUED
                    else "failed",
                    "error_code": code,
                    "error_retryable": retryable,
                    "processing_finished_at": None if replay_status == ReplayStatus.QUEUED else now,
                    "source_delete_after": now
                    + timedelta(hours=self._settings.replay_source_retention_hours),
                    "updated_at": now,
                },
            )
        except ReplayStateConflict:
            latest = await self._replays.get(job.replay_id)
            if latest is not None and ReplayStatus(latest.status) in _PROCESS_CANCEL_STATUSES:
                # Delete won while failure was settling. Keep the failure/retry
                # already recorded above; a later PROCESS attempt will sweep.
                self._metrics.replay_processing_failures_total.inc(error_code=code)
                return

        self._metrics.replay_processing_failures_total.inc(error_code=code)

    async def _fail_job(
        self,
        job: ReplayJobRow,
        *,
        error: Exception,
        retryable: bool,
        now: datetime,
        code: str | None = None,
    ) -> None:
        error_code = code or classify_process_error(error)[0]
        available_at: datetime | None = None
        if retryable and job.attempt_count < job.max_attempts:
            available_at = now + _retry_delay(job.attempt_count)
        updated = await self._jobs.fail(
            job.id,
            error_code=error_code,
            now=now,
            available_at=available_at,
        )
        job.status = updated.status
        if available_at is not None:
            self._metrics.replay_job_retries_total.inc(kind=job.kind)

    async def _transition(
        self,
        row: ReplayUploadRow,
        *,
        expected_statuses: set[ReplayStatus],
        status: ReplayStatus,
        values: dict[str, object],
    ) -> ReplayUploadRow:
        await self._ensure_not_deleting(row)
        try:
            return await self._replays.transition(
                replay_id=row.id,
                expected_statuses=expected_statuses,
                expected_version=row.version,
                status=status,
                values=values,
            )
        except ReplayStateConflict:
            latest = await self._require_replay(row.id)
            await self._ensure_not_deleting(latest)
            raise

    async def _ensure_not_deleting(self, row: ReplayUploadRow) -> None:
        latest = await self._require_replay(row.id)
        if ReplayStatus(latest.status) in _PROCESS_CANCEL_STATUSES:
            raise ReplayProcessingCancelled()

    async def _upload_if_not_deleting(
        self,
        row: ReplayUploadRow,
        key: str,
        source: Path,
    ) -> StoredObject:
        """Upload only while active; roll back objects written after delete wins."""
        await self._ensure_not_deleting(row)
        stored = await self._storage.upload_from_path(key, source)
        try:
            await self._ensure_not_deleting(row)
        except ReplayProcessingCancelled:
            await self._delete_missing_ok(key)
            raise
        return stored

    async def _complete_cancelled_process(self, job: ReplayJobRow) -> None:
        try:
            await self._sweep_cancelled_derived(job.replay_id)
        except Exception as error:
            await self._handle_cancelled_cleanup_failure(job, error)
            return
        await self._jobs.cancel(job.id, now=self._clock())
        job.status = ReplayJobStatus.CANCELLED.value

    async def _handle_cancelled_cleanup_failure(self, job: ReplayJobRow, error: Exception) -> None:
        """Retry cleanup via PROCESS failure semantics without mutating DELETED."""
        await self._handle_process_failure(job, error)

    async def _sweep_cancelled_derived(self, replay_id: UUID) -> None:
        """Idempotent cleanup of PROCESS outputs after cancellation."""
        for prefix in (f"normalized/{replay_id}", f"frames/{replay_id}"):
            await self._storage.delete_prefix(prefix)
        await self._artifacts.delete_rows(replay_id)

    async def _require_replay(self, replay_id: UUID) -> ReplayUploadRow:
        row = await self._replays.get(replay_id)
        if row is None:
            raise ReplayMediaError("REPLAY_MEDIA_UNSUPPORTED", "Replay was not found.")
        return row

    async def _delete_missing_ok(self, key: str) -> None:
        try:
            await self._storage.delete(key)
        except ReplayObjectNotFound:
            return

    def _observe_cleanup_lag(self, deadline: datetime | None, *, now: datetime, kind: str) -> None:
        if deadline is None:
            return
        lag_seconds = max(0.0, (now - deadline).total_seconds())
        self._metrics.replay_cleanup_lag_seconds.observe(lag_seconds, kind=kind)


def extractable_frame_end_ms(*, duration_ms: int, game_time_zero_ms: int) -> int:
    """Return the last game-time that is safe to seek, or reject short anchors."""
    if duration_ms < 0 or game_time_zero_ms < 0:
        raise ValueError("time values must be non-negative")
    remaining_ms = duration_ms - game_time_zero_ms
    if remaining_ms < _FRAME_SEEK_SAFE_MARGIN_MS:
        raise ReplayMediaError(
            "REPLAY_MEDIA_UNSUPPORTED",
            "Replay anchor is too close to the media end for safe frame extraction.",
        )
    return remaining_ms - _FRAME_SEEK_SAFE_MARGIN_MS


def plan_frame_game_times(
    coverage_end_ms: int,
    *,
    max_frames: int = _MAX_FRAMES,
    extractable_end_ms: int | None = None,
) -> list[int]:
    if coverage_end_ms < 0:
        raise ValueError("coverage_end_ms must be non-negative")
    if extractable_end_ms is not None and extractable_end_ms < 0:
        raise ValueError("extractable_end_ms must be non-negative")
    end_ms = (
        coverage_end_ms if extractable_end_ms is None else min(coverage_end_ms, extractable_end_ms)
    )
    times = list(range(0, end_ms + 1, _FRAME_INTERVAL_MS))
    if not times:
        times = [0]
    if times[-1] != end_ms:
        times.append(end_ms)
    return times[:max_frames]


def classify_process_error(error: Exception) -> tuple[str, bool]:
    if isinstance(error, ReplayMediaError):
        retryable = error.code not in _NON_RETRYABLE_MEDIA_CODES
        return error.code, retryable
    if isinstance(error, ReplayObjectNotFound):
        return "REPLAY_MEDIA_UNSUPPORTED", False
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return "REPLAY_STORAGE_UNAVAILABLE", True
    return "REPLAY_PROCESSING_FAILED", False


def _retry_delay(attempt_count: int) -> timedelta:
    base = min(60, 2 ** max(0, attempt_count))
    jitter = random.uniform(0, 0.25 * base)
    return timedelta(seconds=base + jitter)


async def _sha256_file(path: Path) -> str:
    def _digest() -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    return await asyncio.to_thread(_digest)
