from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.models.replay import ReplayJobRow
from app.services.replays.domain import ReplayJobKind, ReplayJobStatus
from app.workers import replay as replay_worker

NOW = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "app_env": "test",
        "replay_enabled": True,
        "replay_token_secret": "x" * 32,
        "replay_worker_concurrency": 1,
        "replay_storage_backend": "local",
        "replay_ffmpeg_path": "ffmpeg",
        "replay_ffprobe_path": "ffprobe",
        "database_url": "postgresql+asyncpg://unused/unused",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _job(*, kind: ReplayJobKind = ReplayJobKind.PROCESS) -> ReplayJobRow:
    return ReplayJobRow(
        id=uuid4(),
        replay_id=uuid4(),
        kind=kind.value,
        status=ReplayJobStatus.PENDING.value,
        attempt_count=0,
        max_attempts=3,
        available_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


@dataclass
class FakeJobRepository:
    events: list[str] = field(default_factory=list)
    claim_results: list[ReplayJobRow | None] = field(default_factory=list)
    heartbeats: list[UUID] = field(default_factory=list)
    recover_calls: int = 0
    retention_calls: list[datetime] = field(default_factory=list)
    succeeded: list[UUID] = field(default_factory=list)

    async def enqueue(self, **kwargs: object) -> ReplayJobRow:
        raise AssertionError("enqueue unexpected")

    async def claim_next(self, *, worker_id: str, now: datetime) -> ReplayJobRow | None:
        self.events.append(f"claim:{worker_id}")
        if self.claim_results:
            return self.claim_results.pop(0)
        return None

    async def heartbeat(self, job_id: UUID, *, worker_id: str, now: datetime) -> None:
        del worker_id, now
        self.heartbeats.append(job_id)
        self.events.append(f"heartbeat:{job_id}")

    async def succeed(self, job_id: UUID, *, now: datetime) -> ReplayJobRow:
        del now
        self.succeeded.append(job_id)
        self.events.append(f"succeed:{job_id}")
        return _job()

    async def fail(self, **kwargs: object) -> ReplayJobRow:
        raise AssertionError("fail unexpected")

    async def cancel(self, **kwargs: object) -> ReplayJobRow:
        raise AssertionError("cancel unexpected")

    async def recover_stale(
        self,
        *,
        heartbeat_before: datetime,
        available_at: datetime,
        now: datetime,
    ) -> int:
        del heartbeat_before, available_at, now
        self.recover_calls += 1
        self.events.append("recover_stale")
        return 0

    async def enqueue_due_retention(self, now: datetime) -> int:
        self.retention_calls.append(now)
        self.events.append("enqueue_due_retention")
        return 0


@dataclass
class FakeProcessor:
    events: list[str] = field(default_factory=list)
    process_started: asyncio.Event = field(default_factory=asyncio.Event)
    process_release: asyncio.Event = field(default_factory=asyncio.Event)
    block_process: bool = False

    async def process(self, job: ReplayJobRow) -> None:
        self.events.append(f"process:{job.id}")
        self.process_started.set()
        if self.block_process:
            await self.process_release.wait()

    async def delete_source(self, job: ReplayJobRow) -> None:
        self.events.append(f"delete_source:{job.id}")

    async def delete_all(self, job: ReplayJobRow) -> None:
        self.events.append(f"delete_all:{job.id}")


@dataclass
class FakeDatabase:
    closed: bool = False

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_worker_idle_backoff_and_recover_stale_on_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    jobs = FakeJobRepository(claim_results=[None, None])
    processor = FakeProcessor()
    database = FakeDatabase()
    sleeps: list[float] = []
    stop = asyncio.Event()
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        if delay == 0.05:
            stop.set()
        await real_sleep(0)

    monkeypatch.setattr(replay_worker.asyncio, "sleep", fake_sleep)

    await replay_worker.run_worker(
        settings,
        stop,
        database=database,
        job_repository=jobs,
        processor=processor,
        idle_backoff_seconds=0.05,
        heartbeat_interval_seconds=15,
        retention_interval_seconds=3600,
        now_factory=lambda: NOW,
    )

    assert jobs.recover_calls == 1
    assert "recover_stale" in jobs.events
    assert 0.05 in sleeps
    assert database.closed is True


@pytest.mark.asyncio
async def test_worker_heartbeats_every_15_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    job = _job()
    job.status = ReplayJobStatus.RUNNING.value
    job.attempt_count = 1
    job.worker_id = "worker-1"
    jobs = FakeJobRepository(claim_results=[job, None])
    processor = FakeProcessor(block_process=True)
    database = FakeDatabase()
    stop = asyncio.Event()
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        if delay == 15 and len(jobs.heartbeats) >= 2:
            processor.process_release.set()
            stop.set()
        await real_sleep(0)

    monkeypatch.setattr(replay_worker.asyncio, "sleep", fake_sleep)

    await replay_worker.run_worker(
        settings,
        stop,
        database=database,
        job_repository=jobs,
        processor=processor,
        idle_backoff_seconds=0.01,
        heartbeat_interval_seconds=15,
        retention_interval_seconds=3600,
        now_factory=lambda: NOW,
        worker_id="worker-1",
    )

    assert len(jobs.heartbeats) >= 2
    assert all(item == job.id for item in jobs.heartbeats)
    assert f"process:{job.id}" in processor.events


@pytest.mark.asyncio
async def test_stop_event_stops_claiming_new_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    first = _job()
    first.status = ReplayJobStatus.RUNNING.value
    first.attempt_count = 1
    second = _job()
    jobs = FakeJobRepository(claim_results=[first, second, None])
    processor = FakeProcessor(block_process=True)
    database = FakeDatabase()
    stop = asyncio.Event()
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        del delay
        if processor.process_started.is_set() and not stop.is_set():
            stop.set()
            processor.process_release.set()
        await real_sleep(0)

    monkeypatch.setattr(replay_worker.asyncio, "sleep", fake_sleep)

    await replay_worker.run_worker(
        settings,
        stop,
        database=database,
        job_repository=jobs,
        processor=processor,
        idle_backoff_seconds=0.01,
        heartbeat_interval_seconds=15,
        retention_interval_seconds=3600,
        now_factory=lambda: NOW,
    )

    assert processor.events.count(f"process:{first.id}") == 1
    assert f"process:{second.id}" not in processor.events


@pytest.mark.asyncio
async def test_retention_scheduler_every_60_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    jobs = FakeJobRepository(claim_results=[])
    processor = FakeProcessor()
    database = FakeDatabase()
    stop = asyncio.Event()
    retention_sleeps = 0
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        nonlocal retention_sleeps
        if delay == 60:
            retention_sleeps += 1
            if retention_sleeps >= 2:
                stop.set()
        await real_sleep(0)

    monkeypatch.setattr(replay_worker.asyncio, "sleep", fake_sleep)

    await replay_worker.run_worker(
        settings,
        stop,
        database=database,
        job_repository=jobs,
        processor=processor,
        idle_backoff_seconds=0.01,
        heartbeat_interval_seconds=15,
        retention_interval_seconds=60,
        now_factory=lambda: NOW,
    )

    assert len(jobs.retention_calls) >= 2
    assert "enqueue_due_retention" in jobs.events


@pytest.mark.asyncio
async def test_check_mode_validates_without_claiming(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _settings(replay_local_root=tmp_path)
    claimed = {"count": 0}

    class GuardedJobs(FakeJobRepository):
        async def claim_next(self, *, worker_id: str, now: datetime) -> ReplayJobRow | None:
            claimed["count"] += 1
            return await super().claim_next(worker_id=worker_id, now=now)

    database = FakeDatabase()
    jobs = GuardedJobs()

    def fake_which(name: str) -> str:
        return f"/usr/bin/{name}"

    monkeypatch.setattr(replay_worker.shutil, "which", fake_which)

    code = await replay_worker.run_check(
        settings,
        database=database,
        job_repository=jobs,
        storage_root=tmp_path,
    )

    assert code == 0
    assert claimed["count"] == 0


@pytest.mark.asyncio
async def test_main_check_flag_exits_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = _settings(replay_local_root=tmp_path)
    monkeypatch.setattr(replay_worker, "Settings", lambda: settings)

    async def fake_check(*args: object, **kwargs: object) -> int:
        del args, kwargs
        return 0

    monkeypatch.setattr(replay_worker, "run_check", fake_check)
    monkeypatch.setattr("sys.argv", ["replay", "--check"])

    with pytest.raises(SystemExit) as exc:
        await replay_worker._amain()
    assert exc.value.code == 0
