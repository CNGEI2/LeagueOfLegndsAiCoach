from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core import metrics as metrics_module
from app.core.config import Settings
from app.core.dependencies import AppServices
from app.core.errors import ApiError
from app.core.logging import bind_safe_request_context
from app.core.metrics import MetricsRegistry
from app.core.routing import Platform
from app.main import create_app
from app.services.analyses.domain import UnavailableReason
from app.services.analyses.metrics import MetricEngine
from app.services.analyses.rules import RuleEngine
from app.services.analyses.scoring import ScoreEngine
from app.services.analyses.service import AnalysisService
from tests.conftest import (
    FakeDatabase,
    FakeMatchService,
    FakePlatformDetectionService,
    FakePlayerService,
    FakeReplayService,
)
from tests.fixtures.analysis_inputs import SELECTED_PUUID, standard_analysis_match
from tests.test_analysis_api import MATCH_ID, SECRET_PUUID, RecordingAnalysisService
from tests.test_analysis_service import NOW, FakeRepository, FakeTimelineService
from tests.test_analysis_service import FakeMatchService as AnalysisMatchService


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        riot_api_key="RGAPI-test",
        joint_evidence_enabled=enabled,
        deterministic_analysis_enabled=enabled,
    )


def _client_with_metrics(
    *,
    analysis: RecordingAnalysisService | None = None,
    enabled: bool = True,
) -> tuple[TestClient, MetricsRegistry, RecordingAnalysisService]:
    registry = MetricsRegistry()
    service = analysis if analysis is not None else RecordingAnalysisService()
    services = AppServices(
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=FakePlatformDetectionService(),
        closers=(),
        analysis_service=service,
    )
    application = create_app(
        settings=_settings(enabled=enabled),
        database=FakeDatabase(),
        services=services,
        replay_metrics=registry,
    )
    return TestClient(application), registry, service


def test_registry_exposes_closed_analysis_series() -> None:
    registry = MetricsRegistry()
    metrics_module.record_analysis_api_request(registry, outcome="ready", error_code="none")
    metrics_module.record_analysis_api_request(
        registry, outcome="error", error_code="MATCH_ANALYSIS_UNSUPPORTED_MODE"
    )
    metrics_module.record_analysis_duration(registry, stage="compute", seconds=0.2)
    metrics_module.record_analysis_duration(registry, stage="persist", seconds=0.1)
    metrics_module.record_analysis_duration(registry, stage="total", seconds=0.3)
    metrics_module.record_analysis_cache(registry, status="hit")
    metrics_module.record_analysis_cache(registry, status="miss")
    metrics_module.record_analysis_result(registry, status="completed")
    metrics_module.record_analysis_result(registry, status="partial")
    metrics_module.record_analysis_coverage(registry, bucket="lt_60")
    metrics_module.record_analysis_coverage(registry, bucket="60_79")
    metrics_module.record_analysis_coverage(registry, bucket="80_99")
    metrics_module.record_analysis_coverage(registry, bucket="100")
    metrics_module.record_analysis_unavailable(registry, reason="timeline_unavailable")
    metrics_module.record_analysis_finding_count(registry, count=2)
    metrics_module.record_analysis_goal_count(registry, count=1)
    metrics_module.record_analysis_idempotency(registry, result="created")
    metrics_module.record_analysis_idempotency(registry, result="reused")

    rendered = registry.render_prometheus_text()
    assert 'analysis_api_requests_total{error_code="none",outcome="ready"} 1.0' in rendered
    assert (
        'analysis_api_requests_total{error_code="MATCH_ANALYSIS_UNSUPPORTED_MODE",outcome="error"}'
        " 1.0" in rendered
    )
    assert "analysis_duration_seconds_count{stage=" in rendered
    assert 'analysis_cache_total{status="hit"} 1.0' in rendered
    assert 'analysis_cache_total{status="miss"} 1.0' in rendered
    assert 'analysis_results_total{status="completed"} 1.0' in rendered
    assert 'analysis_results_total{status="partial"} 1.0' in rendered
    assert 'analysis_coverage_total{bucket="lt_60"} 1.0' in rendered
    assert 'analysis_coverage_total{bucket="60_79"} 1.0' in rendered
    assert 'analysis_coverage_total{bucket="80_99"} 1.0' in rendered
    assert 'analysis_coverage_total{bucket="100"} 1.0' in rendered
    assert 'analysis_unavailable_signals_total{reason="timeline_unavailable"} 1.0' in rendered
    assert "analysis_finding_count 2.0" in rendered
    assert "analysis_goal_count 1.0" in rendered
    assert 'analysis_idempotency_total{result="created"} 1.0' in rendered
    assert 'analysis_idempotency_total{result="reused"} 1.0' in rendered
    for banned in (SELECTED_PUUID, SECRET_PUUID, MATCH_ID, "puuid", "match_id"):
        assert banned not in rendered


def test_analysis_metric_label_allowlists_are_closed() -> None:
    assert frozenset({"ready", "error"}) == AnalysisService.API_OUTCOMES
    assert frozenset({"hit", "miss"}) == AnalysisService.CACHE_STATUSES
    assert frozenset({"completed", "partial"}) == AnalysisService.RESULT_STATUSES
    assert frozenset({"lt_60", "60_79", "80_99", "100"}) == AnalysisService.COVERAGE_BUCKETS
    assert frozenset({"compute", "persist", "total"}) == AnalysisService.STAGES
    assert frozenset({"created", "reused"}) == AnalysisService.IDEMPOTENCY_RESULTS
    assert frozenset(get_args(UnavailableReason)) == AnalysisService.UNAVAILABLE_REASONS
    assert metrics_module.ANALYSIS_API_OUTCOMES == AnalysisService.API_OUTCOMES
    assert "MATCH_ANALYSIS_UNSUPPORTED_MODE" in metrics_module.ANALYSIS_API_ERROR_CODES
    assert "PLAYER_NOT_IN_MATCH" in metrics_module.ANALYSIS_API_ERROR_CODES
    assert "NOT_FOUND" in metrics_module.ANALYSIS_API_ERROR_CODES
    assert "VALIDATION_ERROR" in metrics_module.ANALYSIS_API_ERROR_CODES
    assert "RIOT_INVALID_RESPONSE" in metrics_module.ANALYSIS_API_ERROR_CODES


def test_record_helpers_reject_arbitrary_labels() -> None:
    registry = MetricsRegistry()
    metrics_module.record_analysis_api_request(
        registry, outcome="leaked", error_code=SELECTED_PUUID
    )
    metrics_module.record_analysis_duration(registry, stage=MATCH_ID, seconds=0.01)
    metrics_module.record_analysis_cache(registry, status=SECRET_PUUID)
    metrics_module.record_analysis_result(registry, status="failed")
    metrics_module.record_analysis_coverage(registry, bucket="101")
    metrics_module.record_analysis_unavailable(registry, reason="custom")
    metrics_module.record_analysis_idempotency(registry, result="overwrite")
    rendered = registry.render_prometheus_text()
    assert SELECTED_PUUID not in rendered
    assert SECRET_PUUID not in rendered
    assert MATCH_ID not in rendered
    assert "leaked" not in rendered
    assert "failed" not in rendered
    assert "overwrite" not in rendered
    assert "custom" not in rendered
    assert 'outcome="error"' in rendered
    assert 'error_code="NOT_FOUND"' in rendered


def test_analysis_api_records_ready_and_validation_error() -> None:
    with _client_with_metrics()[0] as client:
        registry = client.app.state.replay_metrics
        invalid = client.post(
            "/api/v1/analyses",
            json={"platform": "NA1", "match_id": MATCH_ID, "puuid": "player-1", "coaching": True},
        )
        assert invalid.status_code == 422
        assert (
            registry.analysis_api_requests_total.value(
                outcome="error", error_code="VALIDATION_ERROR"
            )
            == 1.0
        )
        ready = client.post(
            "/api/v1/analyses",
            json={"platform": "NA1", "match_id": MATCH_ID, "puuid": "player-1"},
        )
        assert ready.status_code == 200
        assert registry.analysis_api_requests_total.value(outcome="ready", error_code="none") == 1.0
        rendered = registry.render_prometheus_text()
        assert SELECTED_PUUID not in rendered
        assert SECRET_PUUID not in ready.text


def test_analysis_api_records_allowlisted_service_errors() -> None:
    analysis = RecordingAnalysisService()
    analysis.error = ApiError(
        status_code=422,
        code="MATCH_ANALYSIS_UNSUPPORTED_MODE",
        message="unsupported",
        retryable=False,
    )
    with _client_with_metrics(analysis=analysis)[0] as client:
        registry = client.app.state.replay_metrics
        response = client.post(
            "/api/v1/analyses",
            json={"platform": "NA1", "match_id": MATCH_ID, "puuid": "player-1"},
        )
        assert response.status_code == 422
        assert (
            registry.analysis_api_requests_total.value(
                outcome="error", error_code="MATCH_ANALYSIS_UNSUPPORTED_MODE"
            )
            == 1.0
        )


@pytest.mark.asyncio
async def test_analysis_service_records_closed_compute_metrics() -> None:
    registry = MetricsRegistry()
    times = iter([10.0, 10.4, 10.7, 11.0, 11.1])
    service = AnalysisService(
        match_service=AnalysisMatchService(snapshot=standard_analysis_match()),
        timeline_service=FakeTimelineService(),
        repository=FakeRepository(),
        metric_engine=MetricEngine(),
        score_engine=ScoreEngine(),
        rule_engine=RuleEngine(),
        retention_days=30,
        clock=lambda: NOW,
        metrics=registry,
        monotonic=lambda: next(times),
    )
    analysis_id, result, created = await service.create_or_reuse(
        platform=Platform.NA1, match_id="NA1_ANALYSIS_FIXTURE", puuid=SELECTED_PUUID
    )
    assert created is True
    assert result.status == "completed"
    assert registry.analysis_duration_seconds.count(stage="compute") == 1
    assert registry.analysis_duration_seconds.count(stage="persist") == 1
    assert registry.analysis_duration_seconds.count(stage="total") == 1
    assert pytest.approx(registry.analysis_duration_seconds.sum(stage="compute")) == 0.4
    assert pytest.approx(registry.analysis_duration_seconds.sum(stage="persist")) == 0.3
    assert pytest.approx(registry.analysis_duration_seconds.sum(stage="total")) == 0.7
    assert registry.analysis_cache_total.value(status="miss") == 1.0
    assert registry.analysis_idempotency_total.value(result="created") == 1.0
    assert registry.analysis_results_total.value(status="completed") == 1.0
    assert registry.analysis_coverage_total.value(bucket="100") == 1.0
    rendered = registry.render_prometheus_text()
    assert SELECTED_PUUID not in rendered
    assert "NA1_ANALYSIS_FIXTURE" not in rendered

    loaded = await service.get(analysis_id=analysis_id)
    assert loaded == result
    assert registry.analysis_cache_total.value(status="hit") == 1.0


@pytest.mark.asyncio
async def test_analysis_service_emits_safe_structured_create_log(caplog) -> None:  # type: ignore[no-untyped-def]
    times = iter([10.0, 10.4, 10.7])
    service = AnalysisService(
        match_service=AnalysisMatchService(snapshot=standard_analysis_match()),
        timeline_service=FakeTimelineService(),
        repository=FakeRepository(),
        metric_engine=MetricEngine(),
        score_engine=ScoreEngine(),
        rule_engine=RuleEngine(),
        retention_days=30,
        clock=lambda: NOW,
        monotonic=lambda: next(times),
        logger=logging.getLogger("lol_ai_coach.analysis.test"),
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/analyses",
            "headers": [],
            "route": SimpleNamespace(path="/api/v1/analyses"),
        }
    )
    request.state.request_id = "request-analysis-safe-log"
    dependency = bind_safe_request_context(request)
    await anext(dependency)
    try:
        with caplog.at_level(logging.INFO, logger="lol_ai_coach.analysis.test"):
            await service.create_or_reuse(
                platform=Platform.NA1,
                match_id="NA1_ANALYSIS_FIXTURE",
                puuid=SELECTED_PUUID,
            )
    finally:
        await dependency.aclose()

    payload = json.loads(caplog.messages[-1])
    assert payload == {
        "cache_status": "miss",
        "event": "deterministic_analysis",
        "latency_ms": 700,
        "metric_version": "deterministic-metrics-v1",
        "player_reference_hash": payload["player_reference_hash"],
        "request_id": "request-analysis-safe-log",
        "retry_count": 0,
        "route": "/api/v1/analyses",
        "rules_version": "deterministic-rules-v1",
        "safe_status": "completed",
        "score_version": "deterministic-score-v1",
        "upstream": "local",
    }
    assert len(payload["player_reference_hash"]) == 16
    assert SELECTED_PUUID not in caplog.text
    assert "NA1_ANALYSIS_FIXTURE" not in caplog.text
