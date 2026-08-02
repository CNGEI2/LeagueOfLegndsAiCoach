from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import AppServices
from app.core.metrics import Counter, Gauge, Histogram, MetricsRegistry
from app.main import create_app
from app.services.replays.domain import ReplayJobKind, ReplayJobStatus, ReplayStatus
from app.services.replays.processor import ReplayProcessor
from tests.conftest import FakeDatabase
from tests.test_replay_processor import (
    NOW,
    FakeMediaRunner,
    FakeReplayArtifactRepository,
    FakeReplayJobRepository,
    FakeReplayRepository,
    FakeReplayStorage,
    _job,
    _replay,
    _settings,
)

# ---------------------------------------------------------------------------
# Metrics primitives
# ---------------------------------------------------------------------------


def test_counter_increments_and_tracks_labels_independently() -> None:
    counter = Counter("replay_test_total", "test counter")

    counter.inc(error_code="A")
    counter.inc(error_code="A")
    counter.inc(error_code="B")

    assert counter.value(error_code="A") == 2
    assert counter.value(error_code="B") == 1
    assert counter.value(error_code="C") == 0


def test_gauge_set_overwrites_previous_value_per_label() -> None:
    gauge = Gauge("replay_test_gauge", "test gauge")

    gauge.set(3.0, kind="source")
    gauge.set(7.5, kind="source")
    gauge.set(1.0, kind="all")

    assert gauge.value(kind="source") == 7.5
    assert gauge.value(kind="all") == 1.0


def test_histogram_observes_into_correct_buckets_and_tracks_sum_count() -> None:
    histogram = Histogram("replay_test_duration_seconds", "test", buckets=(1.0, 5.0, 10.0))

    histogram.observe(0.5, stage="total")
    histogram.observe(3.0, stage="total")
    histogram.observe(20.0, stage="total")

    assert histogram.count(stage="total") == 3
    assert histogram.sum(stage="total") == pytest.approx(23.5)


class IncrementingClock:
    def __init__(self, start: datetime, step: timedelta = timedelta(seconds=1)) -> None:
        self._current = start
        self._step = step

    def __call__(self) -> datetime:
        value = self._current
        self._current = self._current + self._step
        return value


def _processor_with_metrics(
    *,
    replay,
    metrics: MetricsRegistry,
    storage: FakeReplayStorage | None = None,
    media: FakeMediaRunner | None = None,
    clock=None,
) -> tuple[ReplayProcessor, FakeReplayRepository, FakeReplayJobRepository]:
    replay_repo = FakeReplayRepository(rows={replay.id: replay})
    job_repo = FakeReplayJobRepository()
    artifact_repo = FakeReplayArtifactRepository()
    store = storage or FakeReplayStorage()
    if replay.source_object_key and replay.source_object_key not in store.objects:
        store.objects[replay.source_object_key] = b"source-video-bytes"
    media_runner = media or FakeMediaRunner()
    processor = ReplayProcessor(
        settings=_settings(),
        replay_repository=replay_repo,
        job_repository=job_repo,
        artifact_repository=artifact_repo,
        storage=store,
        media=media_runner,
        clock=clock or (lambda: NOW),
        metrics=metrics,
    )
    return processor, replay_repo, job_repo


@pytest.mark.asyncio
async def test_successful_process_records_total_processing_duration() -> None:
    replay = _replay(match_duration_ms=60_000, game_time_zero_ms=1_000)
    metrics = MetricsRegistry()
    processor, _replay_repo, job_repo = _processor_with_metrics(
        replay=replay,
        metrics=metrics,
        clock=IncrementingClock(NOW),
    )
    job = _job(replay.id)
    job_repo.jobs[job.id] = job

    await processor.process(job)

    assert job.status == ReplayJobStatus.SUCCEEDED.value
    assert metrics.replay_processing_duration_seconds.count(stage="total") == 1
    assert metrics.replay_processing_duration_seconds.sum(stage="total") > 0


@pytest.mark.asyncio
async def test_non_retryable_failure_increments_failures_by_error_code() -> None:
    replay = _replay(match_duration_ms=60_000, game_time_zero_ms=1_000)
    metrics = MetricsRegistry()
    media = FakeMediaRunner(fail_normalize=True)
    processor, replay_repo, job_repo = _processor_with_metrics(
        replay=replay, metrics=metrics, media=media
    )
    job = _job(replay.id, attempt_count=1)
    job_repo.jobs[job.id] = job

    await processor.process(job)

    assert replay_repo.rows[replay.id].status == ReplayStatus.FAILED.value
    assert job.status == ReplayJobStatus.FAILED.value
    failures = metrics.replay_processing_failures_total.value(error_code="REPLAY_PROCESSING_FAILED")
    assert failures == 1
    assert metrics.replay_job_retries_total.value(kind=ReplayJobKind.PROCESS.value) == 0


@pytest.mark.asyncio
async def test_retryable_failure_increments_failures_and_schedules_a_retry() -> None:
    replay = _replay(match_duration_ms=60_000, game_time_zero_ms=1_000)
    metrics = MetricsRegistry()
    storage = FakeReplayStorage(fail_upload_times=1)
    processor, _replay_repo, job_repo = _processor_with_metrics(
        replay=replay, metrics=metrics, storage=storage
    )
    job = _job(replay.id, attempt_count=1)
    job_repo.jobs[job.id] = job

    await processor.process(job)

    assert job.status == ReplayJobStatus.RETRY_SCHEDULED.value
    failures = metrics.replay_processing_failures_total.value(
        error_code="REPLAY_STORAGE_UNAVAILABLE"
    )
    assert failures == 1
    assert metrics.replay_job_retries_total.value(kind=ReplayJobKind.PROCESS.value) == 1


@pytest.mark.asyncio
async def test_delete_source_records_cleanup_lag_against_source_delete_after() -> None:
    deadline = NOW - timedelta(minutes=5)
    replay = _replay(
        match_duration_ms=60_000,
        game_time_zero_ms=1_000,
        status=ReplayStatus.READY.value,
        source_delete_after=deadline,
    )
    metrics = MetricsRegistry()
    processor, _replay_repo, job_repo = _processor_with_metrics(replay=replay, metrics=metrics)
    job = _job(replay.id, kind=ReplayJobKind.DELETE_SOURCE)
    job_repo.jobs[job.id] = job

    await processor.delete_source(job)

    assert job.status == ReplayJobStatus.SUCCEEDED.value
    assert metrics.replay_cleanup_lag_seconds.count(kind="source") == 1
    assert metrics.replay_cleanup_lag_seconds.sum(kind="source") == pytest.approx(300.0)


@pytest.mark.asyncio
async def test_delete_all_records_cleanup_lag_against_derived_delete_after() -> None:
    deadline = NOW - timedelta(hours=1)
    replay = _replay(
        match_duration_ms=60_000,
        game_time_zero_ms=1_000,
        status=ReplayStatus.DELETING.value,
        derived_delete_after=deadline,
        normalized_object_key=None,
    )
    metrics = MetricsRegistry()
    processor, _replay_repo, job_repo = _processor_with_metrics(replay=replay, metrics=metrics)
    job = _job(replay.id, kind=ReplayJobKind.DELETE_ALL)
    job_repo.jobs[job.id] = job

    await processor.delete_all(job)

    assert job.status == ReplayJobStatus.SUCCEEDED.value
    assert metrics.replay_cleanup_lag_seconds.count(kind="all") == 1
    assert metrics.replay_cleanup_lag_seconds.sum(kind="all") == pytest.approx(3600.0)


@pytest.mark.asyncio
async def test_delete_all_skips_cleanup_lag_when_no_deadline_present() -> None:
    replay = _replay(
        match_duration_ms=60_000,
        game_time_zero_ms=1_000,
        status=ReplayStatus.DELETING.value,
        derived_delete_after=None,
        source_delete_after=None,
        normalized_object_key=None,
    )
    metrics = MetricsRegistry()
    processor, _replay_repo, job_repo = _processor_with_metrics(replay=replay, metrics=metrics)
    job = _job(replay.id, kind=ReplayJobKind.DELETE_ALL)
    job_repo.jobs[job.id] = job

    await processor.delete_all(job)

    assert job.status == ReplayJobStatus.SUCCEEDED.value
    assert metrics.replay_cleanup_lag_seconds.count(kind="all") == 0


# ---------------------------------------------------------------------------
# Internal metrics endpoint
# ---------------------------------------------------------------------------


def _metrics_app_settings(**overrides: object):
    from app.core.config import Settings

    values: dict[str, object] = {
        "_env_file": None,
        "app_env": "test",
        "database_url": "postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        "riot_api_key": "RGAPI-test",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _metrics_app(**settings_overrides: object) -> tuple[TestClient, MetricsRegistry]:
    registry = MetricsRegistry()
    registry.replay_processing_failures_total.inc(error_code="REPLAY_PROCESSING_FAILED")
    registry.replay_processing_duration_seconds.observe(12.5, stage="total")

    settings = _metrics_app_settings(**settings_overrides)
    services = AppServices(
        player_service=object(),  # type: ignore[arg-type]
        match_service=object(),  # type: ignore[arg-type]
        replay_service=object(),  # type: ignore[arg-type]
        closers=(),
    )
    application = create_app(
        settings=settings,
        database=FakeDatabase(),
        services=services,
        replay_metrics=registry,
    )
    return TestClient(application), registry


def test_internal_metrics_endpoint_renders_prometheus_text_with_valid_bearer_token() -> None:
    client, _registry = _metrics_app(internal_metrics_token="test-metrics-token")

    with client:
        response = client.get(
            "/internal/metrics",
            headers={"Authorization": "Bearer test-metrics-token"},
        )

    assert response.status_code == 200
    body = response.text
    assert "# TYPE replay_processing_failures_total counter" in body
    assert 'replay_processing_failures_total{error_code="REPLAY_PROCESSING_FAILED"} 1' in body
    assert "# TYPE replay_processing_duration_seconds histogram" in body
    assert 'replay_processing_duration_seconds_sum{stage="total"} 12.5' in body
    assert 'replay_processing_duration_seconds_count{stage="total"} 1' in body


def test_internal_metrics_endpoint_returns_404_when_token_is_not_configured() -> None:
    # Fail closed: with no token configured, the endpoint must not exist at
    # all rather than silently serve metrics to anyone on the network.
    client, _registry = _metrics_app(internal_metrics_token="")

    with client:
        response = client.get("/internal/metrics")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INTERNAL_METRICS_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": "Basic dGVzdC1tZXRyaWNzLXRva2Vu"},
        {"Authorization": "Bearer"},
    ],
)
def test_internal_metrics_endpoint_returns_401_for_missing_or_wrong_bearer_token(
    headers: dict[str, str],
) -> None:
    client, _registry = _metrics_app(internal_metrics_token="test-metrics-token")

    with client:
        response = client.get("/internal/metrics", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INTERNAL_METRICS_UNAUTHORIZED"
