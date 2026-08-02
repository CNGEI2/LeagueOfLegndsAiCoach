from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import signal
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.core.config import Settings
from app.core.database import Database
from app.core.metrics import MetricsRegistry
from app.models.replay import ReplayJobRow
from app.repositories.replays import (
    ReplayJobRepository,
    SqlReplayArtifactRepository,
    SqlReplayJobRepository,
    SqlReplayRepository,
)
from app.services.replays.domain import ReplayJobKind
from app.services.replays.media import ReplayMediaRunner
from app.services.replays.processor import ReplayProcessor
from app.services.replays.storage.base import ReplayStorage
from app.services.replays.storage.factory import build_replay_storage

logger = logging.getLogger(__name__)

_STALE_HEARTBEAT = timedelta(seconds=60)


async def run_worker(
    settings: Settings,
    stop_event: asyncio.Event,
    *,
    database: Database | None = None,
    job_repository: ReplayJobRepository | None = None,
    processor: ReplayProcessor | None = None,
    storage: ReplayStorage | None = None,
    idle_backoff_seconds: float = 1.0,
    heartbeat_interval_seconds: float = 15.0,
    retention_interval_seconds: float = 60.0,
    now_factory: Callable[[], datetime] | None = None,
    worker_id: str | None = None,
    metrics: MetricsRegistry | None = None,
) -> None:
    if not settings.replay_enabled:
        raise RuntimeError("replay worker requires REPLAY_ENABLED=true")

    clock = now_factory or (lambda: datetime.now(UTC))
    db = database or Database(settings.database_url)
    jobs = job_repository or SqlReplayJobRepository(db.session_factory)
    resolved_worker_id = worker_id or f"replay-worker-{uuid.uuid4().hex[:12]}"

    if processor is None:
        storage_adapter = storage or build_replay_storage(settings)
        media = ReplayMediaRunner(
            ffmpeg_path=settings.replay_ffmpeg_path,
            ffprobe_path=settings.replay_ffprobe_path,
            timeout_seconds=float(settings.replay_process_timeout_seconds),
        )
        processor = ReplayProcessor(
            settings=settings,
            replay_repository=SqlReplayRepository(db.session_factory),
            job_repository=jobs,
            artifact_repository=SqlReplayArtifactRepository(db.session_factory),
            storage=storage_adapter,
            media=media,
            clock=clock,
            metrics=metrics,
        )

    now = clock()
    await jobs.recover_stale(
        heartbeat_before=now - _STALE_HEARTBEAT,
        available_at=now + timedelta(seconds=1),
        now=now,
        source_delete_after=now + timedelta(hours=settings.replay_source_retention_hours),
    )

    retention_task = asyncio.create_task(
        _retention_loop(
            jobs,
            stop_event,
            interval_seconds=retention_interval_seconds,
            now_factory=clock,
        )
    )
    consumers = [
        asyncio.create_task(
            _consumer_loop(
                processor=processor,
                jobs=jobs,
                stop_event=stop_event,
                worker_id=f"{resolved_worker_id}-{index}",
                idle_backoff_seconds=idle_backoff_seconds,
                heartbeat_interval_seconds=heartbeat_interval_seconds,
                now_factory=clock,
            )
        )
        for index in range(max(1, settings.replay_worker_concurrency))
    ]

    try:
        await stop_event.wait()
    finally:
        retention_task.cancel()
        await asyncio.gather(retention_task, return_exceptions=True)
        # Do not cancel consumers here. A SIGTERM must stop new claims while
        # allowing an already-dispatched ffmpeg job to finish; Docker's
        # stop_grace_period remains the hard outer bound for a stuck process.
        await asyncio.gather(*consumers, return_exceptions=True)
        await db.close()


async def run_check(
    settings: Settings,
    *,
    database: Database | None = None,
    job_repository: ReplayJobRepository | None = None,
    storage_root: Path | None = None,
) -> int:
    del job_repository  # check mode must never claim jobs
    if not settings.replay_enabled:
        raise RuntimeError("replay check requires REPLAY_ENABLED=true")

    own_database = database is None
    db = database or Database(settings.database_url)
    try:
        await db.ping()
        build_replay_storage(settings)
        scratch_root = storage_root or Path(tempfile_scratch_root())
        scratch_root.mkdir(parents=True, exist_ok=True)
        probe = scratch_root / f".replay-check-{uuid.uuid4().hex}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        if shutil.which(settings.replay_ffmpeg_path) is None:
            raise RuntimeError("ffmpeg is unavailable")
        if shutil.which(settings.replay_ffprobe_path) is None:
            raise RuntimeError("ffprobe is unavailable")
    finally:
        if own_database:
            await db.close()
    return 0


def tempfile_scratch_root() -> str:
    import tempfile

    return tempfile.gettempdir()


async def _consumer_loop(
    *,
    processor: ReplayProcessor,
    jobs: ReplayJobRepository,
    stop_event: asyncio.Event,
    worker_id: str,
    idle_backoff_seconds: float,
    heartbeat_interval_seconds: float,
    now_factory: Callable[[], datetime],
) -> None:
    while not stop_event.is_set():
        if stop_event.is_set():
            break
        job = await jobs.claim_next(worker_id=worker_id, now=now_factory())
        if job is None:
            await _wait_for_stop(stop_event, idle_backoff_seconds)
            continue

        job_finished = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            _heartbeat_loop(
                jobs,
                job_id=job.id,
                worker_id=worker_id,
                interval_seconds=heartbeat_interval_seconds,
                job_finished=job_finished,
                now_factory=now_factory,
            )
        )
        try:
            await _dispatch(processor, job)
        finally:
            job_finished.set()
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)


async def _dispatch(processor: ReplayProcessor, job: ReplayJobRow) -> None:
    kind = ReplayJobKind(job.kind)
    if kind == ReplayJobKind.PROCESS:
        await processor.process(job)
    elif kind == ReplayJobKind.DELETE_SOURCE:
        await processor.delete_source(job)
    elif kind == ReplayJobKind.DELETE_ALL:
        await processor.delete_all(job)
    else:
        raise RuntimeError(f"unsupported replay job kind: {job.kind}")


async def _heartbeat_loop(
    jobs: ReplayJobRepository,
    *,
    job_id: UUID,
    worker_id: str,
    interval_seconds: float,
    job_finished: asyncio.Event,
    now_factory: Callable[[], datetime],
) -> None:
    while not job_finished.is_set():
        await asyncio.sleep(interval_seconds)
        if job_finished.is_set():
            break
        await jobs.heartbeat(job_id, worker_id=worker_id, now=now_factory())


async def _retention_loop(
    jobs: ReplayJobRepository,
    stop_event: asyncio.Event,
    *,
    interval_seconds: float,
    now_factory: Callable[[], datetime],
) -> None:
    while not stop_event.is_set():
        await jobs.enqueue_due_retention(now_factory())
        await _wait_for_stop(stop_event, interval_seconds)


async def _wait_for_stop(stop_event: asyncio.Event, timeout_seconds: float) -> None:
    """Sleep until the next interval or return immediately during shutdown."""
    if stop_event.is_set():
        return
    stop_waiter = asyncio.create_task(stop_event.wait())
    sleeper = asyncio.create_task(asyncio.sleep(timeout_seconds))
    done, pending = await asyncio.wait(
        {stop_waiter, sleeper},
        return_when=asyncio.FIRST_COMPLETED,
    )
    del done
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


async def _amain(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.workers.replay")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate worker dependencies and exit without claiming jobs",
    )
    args = parser.parse_args(argv)
    settings = Settings()

    if args.check:
        code = await run_check(settings)
        raise SystemExit(code)

    if not settings.replay_enabled:
        raise SystemExit("REPLAY_ENABLED must be true for the replay worker")
    if shutil.which(settings.replay_ffmpeg_path) is None:
        raise SystemExit("ffmpeg is unavailable")
    if shutil.which(settings.replay_ffprobe_path) is None:
        raise SystemExit("ffprobe is unavailable")
    build_replay_storage(settings)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: stop_event.set())

    await run_worker(settings, stop_event)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(_amain())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        raise SystemExit(0) from None


if __name__ == "__main__":
    main()
