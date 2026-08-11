from __future__ import annotations

import asyncio

import pytest

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.metrics import MetricsRegistry
from app.core.routing import Platform
from app.services.timelines.service import TimelineService
from tests.test_timeline_service import (
    FakeTimelineGateway,
    FakeTimelineRepository,
    MonotonicClock,
    _api_error,
    make_service,
)


def test_joint_evidence_feature_flag_defaults_false() -> None:
    assert Settings(_env_file=None).joint_evidence_enabled is False


def test_registry_exposes_closed_joint_evidence_timeline_metrics() -> None:
    registry = MetricsRegistry()
    registry.joint_evidence_timeline_requests_total.inc(outcome="available")
    registry.joint_evidence_timeline_cache_total.inc(status="hit")
    registry.joint_evidence_timeline_fetch_duration_seconds.observe(0.2, outcome="available")
    registry.joint_evidence_timeline_events_total.inc(
        event_type="champion_kill", result="supported"
    )
    registry.joint_evidence_timeline_events_total.inc(event_type="unknown", result="ignored")
    registry.joint_evidence_singleflight_total.inc(result="leader")

    rendered = registry.render_prometheus_text()
    assert 'joint_evidence_timeline_requests_total{outcome="available"} 1.0' in rendered
    assert 'joint_evidence_timeline_cache_total{status="hit"} 1.0' in rendered
    assert "joint_evidence_timeline_fetch_duration_seconds" in rendered
    assert (
        'joint_evidence_timeline_events_total{event_type="champion_kill",result="supported"} 1.0'
        in rendered
    )
    assert (
        'joint_evidence_timeline_events_total{event_type="unknown",result="ignored"} 1.0'
        in rendered
    )
    assert 'joint_evidence_singleflight_total{result="leader"} 1.0' in rendered


def test_metric_label_allowlists_are_closed() -> None:
    assert (
        frozenset(
            {
                "available",
                "not_found",
                "auth_failed",
                "rate_limited",
                "invalid_response",
                "unavailable",
                "internal_error",
            }
        )
        == TimelineService.REQUEST_OUTCOMES
    )
    assert frozenset({"hit", "miss", "not_found"}) == TimelineService.CACHE_STATUSES
    assert (
        frozenset(
            {
                "available",
                "not_found",
                "auth_failed",
                "rate_limited",
                "invalid_response",
                "unavailable",
            }
        )
        == TimelineService.FETCH_OUTCOMES
    )
    assert (
        frozenset(
            {
                "champion_kill",
                "elite_monster_kill",
                "building_kill",
                "item_purchased",
                "item_sold",
                "item_destroyed",
                "item_undo",
                "participant_state",
                "unknown",
            }
        )
        == TimelineService.EVENT_TYPES
    )
    assert frozenset({"supported", "ignored"}) == TimelineService.EVENT_RESULTS
    assert (
        frozenset({"leader", "waiter", "shared_success", "shared_failure"})
        == TimelineService.SINGLEFLIGHT_RESULTS
    )


@pytest.mark.asyncio
async def test_service_records_closed_timeline_metrics_without_unsafe_labels() -> None:
    metrics = MetricsRegistry()
    monotonic = MonotonicClock([10.0, 10.5, 11.0, 11.5, 12.0, 12.5])
    service, repository, gateway, _ = make_service(metrics=metrics, monotonic=monotonic)

    await service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")
    await service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")

    assert metrics.joint_evidence_timeline_cache_total.value(status="miss") == 1.0
    assert metrics.joint_evidence_timeline_cache_total.value(status="hit") == 1.0
    assert metrics.joint_evidence_timeline_requests_total.value(outcome="available") == 2.0
    assert metrics.joint_evidence_timeline_fetch_duration_seconds.count(outcome="available") == 1
    assert metrics.joint_evidence_timeline_fetch_duration_seconds.sum(outcome="available") == 0.5
    assert (
        metrics.joint_evidence_timeline_events_total.value(
            event_type="champion_kill", result="supported"
        )
        == 2.0
    )
    assert (
        metrics.joint_evidence_timeline_events_total.value(
            event_type="participant_state", result="supported"
        )
        == 20.0
    )
    assert (
        metrics.joint_evidence_timeline_events_total.value(event_type="unknown", result="ignored")
        == 1.0
    )
    assert metrics.joint_evidence_singleflight_total.value(result="leader") == 1.0
    assert metrics.joint_evidence_singleflight_total.value(result="shared_success") == 1.0

    rendered = metrics.render_prometheus_text()
    forbidden = [
        "NA1",
        "NA1_fixture",
        "fixture-puuid",
        "americas.api.riotgames.com",
        "https://",
        "DRAGON",
        "safe upstream",
        str(repository.upserts[0].snapshot_hash),
    ]
    for token in forbidden:
        assert token not in rendered


@pytest.mark.asyncio
async def test_service_records_not_found_and_upstream_failure_outcomes() -> None:
    metrics = MetricsRegistry()
    gateway = FakeTimelineGateway()
    gateway.error = _api_error("MATCH_TIMELINE_NOT_FOUND", status_code=404)
    service, _, _, _ = make_service(metrics=metrics, gateway=gateway)

    with pytest.raises(ApiError):
        await service.get_timeline(platform=Platform.NA1, match_id="NA1_missing")
    assert metrics.joint_evidence_timeline_cache_total.value(status="miss") == 1.0
    assert metrics.joint_evidence_timeline_cache_total.value(status="not_found") == 0.0
    assert metrics.joint_evidence_timeline_requests_total.value(outcome="not_found") == 1.0
    assert metrics.joint_evidence_timeline_fetch_duration_seconds.count(outcome="not_found") == 1

    with pytest.raises(ApiError):
        await service.get_timeline(platform=Platform.NA1, match_id="NA1_missing")
    assert metrics.joint_evidence_timeline_cache_total.value(status="not_found") == 1.0
    assert metrics.joint_evidence_timeline_requests_total.value(outcome="not_found") == 2.0

    metrics = MetricsRegistry()
    gateway = FakeTimelineGateway()
    gateway.error = _api_error("RIOT_AUTH_FAILED", status_code=503)
    service, repository, _, _ = make_service(metrics=metrics, gateway=gateway)
    with pytest.raises(ApiError):
        await service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")
    assert metrics.joint_evidence_timeline_requests_total.value(outcome="auth_failed") == 1.0
    assert metrics.joint_evidence_timeline_fetch_duration_seconds.count(outcome="auth_failed") == 1
    assert repository.upserts == []
    rendered = metrics.render_prometheus_text()
    assert "NA1_fixture" not in rendered
    assert "RIOT_AUTH_FAILED" not in rendered


@pytest.mark.asyncio
async def test_singleflight_waiter_and_shared_failure_metrics_use_event_barrier() -> None:
    metrics = MetricsRegistry()
    gateway = FakeTimelineGateway()
    gateway.started = asyncio.Event()
    gateway.release = asyncio.Event()
    gateway.error = _api_error("RIOT_UNAVAILABLE", status_code=503, retryable=True)
    service, _, _, _ = make_service(metrics=metrics, gateway=gateway)

    first = asyncio.create_task(service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture"))
    await gateway.started.wait()
    second = asyncio.create_task(
        service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")
    )
    await asyncio.sleep(0)
    gateway.release.set()
    results = await asyncio.gather(first, second, return_exceptions=True)
    assert all(isinstance(result, ApiError) for result in results)
    assert metrics.joint_evidence_singleflight_total.value(result="leader") == 1.0
    assert metrics.joint_evidence_singleflight_total.value(result="waiter") == 1.0
    assert metrics.joint_evidence_singleflight_total.value(result="shared_failure") == 1.0
    assert metrics.joint_evidence_timeline_requests_total.value(outcome="unavailable") == 2.0


@pytest.mark.asyncio
async def test_shared_task_cancellation_records_shared_failure_and_allows_retry() -> None:
    metrics = MetricsRegistry()
    gateway = FakeTimelineGateway()
    gateway.started = asyncio.Event()
    gateway.release = asyncio.Event()
    service, _, _, _ = make_service(metrics=metrics, gateway=gateway)

    leader = asyncio.create_task(
        service.get_timeline(platform=Platform.NA1, match_id="NA1_cancel_shared")
    )
    await gateway.started.wait()
    shared = next(iter(service._inflight.values()))
    shared.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leader
    assert service._inflight == {}
    assert metrics.joint_evidence_singleflight_total.value(result="shared_failure") == 1.0
    assert metrics.joint_evidence_timeline_requests_total.samples() == []
    gateway.release.set()

    retry = await service.get_timeline(platform=Platform.NA1, match_id="NA1_cancel_shared")
    assert retry.cache_status == "miss"
    assert metrics.joint_evidence_singleflight_total.value(result="leader") == 2.0
    assert metrics.joint_evidence_singleflight_total.value(result="shared_success") == 1.0
    assert metrics.joint_evidence_timeline_requests_total.value(outcome="available") == 1.0


@pytest.mark.asyncio
async def test_repository_write_failure_records_internal_error_and_available_fetch() -> None:
    metrics = MetricsRegistry()
    monotonic = MonotonicClock([10.0, 10.5, 11.0, 11.5])
    repository = FakeTimelineRepository()
    repository.upsert_error = RuntimeError("db write failed")
    service, repository, gateway, normalizer = make_service(
        repository=repository, metrics=metrics, monotonic=monotonic
    )

    with pytest.raises(RuntimeError, match="db write failed"):
        await service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")

    assert gateway.calls == [(Platform.NA1, "NA1_fixture")]
    assert normalizer.calls == 1
    assert repository.upserts == []
    assert repository.records == {}
    assert metrics.joint_evidence_timeline_requests_total.value(outcome="internal_error") == 1.0
    request_total = sum(
        value for _, value in metrics.joint_evidence_timeline_requests_total.samples()
    )
    assert request_total == 1.0
    assert metrics.joint_evidence_timeline_fetch_duration_seconds.count(outcome="available") == 1
    assert metrics.joint_evidence_timeline_fetch_duration_seconds.sum(outcome="available") == 0.5
    assert metrics.joint_evidence_timeline_events_total.samples() == []
    assert metrics.joint_evidence_timeline_cache_total.value(status="miss") == 1.0
