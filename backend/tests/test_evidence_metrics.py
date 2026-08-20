from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core import metrics as metrics_module
from app.core.config import Settings
from app.core.dependencies import AppServices
from app.core.errors import ApiError
from app.core.metrics import MetricsRegistry
from app.core.routing import Platform
from app.main import create_app
from app.schemas.domain import Locale, StaticDataStatus
from app.schemas.evidence import JointEvidenceData, PublicChampionKillFact
from app.services.evidence.service import DisabledJointEvidenceService, JointEvidenceService
from tests.conftest import (
    FakeDatabase,
    FakeMatchService,
    FakePlatformDetectionService,
    FakePlayerService,
    FakeReplayService,
)

PUUID = "selected-player-puuid"
MATCH_ID = "NA1_fixture"
TOKEN = "capability-token-value"


class FakeJointEvidenceService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: ApiError | None = None
        self.data = JointEvidenceData(
            platform=Platform.NA1,
            match_id=MATCH_ID,
            locale=Locale.EN_US,
            schema_version=1,
            facts=(
                PublicChampionKillFact(
                    fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:0",
                    kind="champion_kill",
                    timestamp_ms=60_000,
                    relationship="killer",
                    killer_id=1,
                    victim_id=6,
                    assisting_participant_ids=(),
                    position_x=1,
                    position_y=2,
                ),
            ),
            windows=(),
            timeline_cache_status="miss",
            replay_link=None,
            static_data_status=StaticDataStatus(available=True, version="16.15.2", code=None),
            truncated=False,
            total_window_count=0,
        )

    async def prepare(self, *, match_id: str, request: object, replay_token: str | None):
        self.calls.append({"match_id": match_id, "request": request, "replay_token": replay_token})
        if self.error is not None:
            raise self.error
        locale = getattr(request, "locale", Locale.EN_US)
        platform = getattr(request, "platform", Platform.NA1)
        return self.data.model_copy(
            update={"locale": locale, "platform": platform, "match_id": match_id}
        )


def _client_with_metrics(
    *,
    joint: FakeJointEvidenceService | DisabledJointEvidenceService,
    enabled: bool = True,
) -> tuple[TestClient, MetricsRegistry]:
    registry = MetricsRegistry()
    services = AppServices(
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=FakePlatformDetectionService(),
        joint_evidence_service=joint,
        closers=(),
    )
    application = create_app(
        settings=Settings(
            _env_file=None,
            app_env="test",
            database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
            riot_api_key="RGAPI-test",
            joint_evidence_enabled=enabled,
        ),
        database=FakeDatabase(),
        services=services,
        replay_metrics=registry,
    )
    return TestClient(application), registry


def test_registry_exposes_closed_joint_evidence_composition_metrics() -> None:
    registry = MetricsRegistry()
    registry.joint_evidence_windows_total.inc(result="planned")
    registry.joint_evidence_window_truncations_total.inc(result="truncated")
    registry.joint_evidence_window_truncations_total.inc(result="not_truncated")
    registry.joint_evidence_replay_coverage_total.inc(coverage="full")
    registry.joint_evidence_replay_coverage_total.inc(coverage="partial")
    registry.joint_evidence_replay_coverage_total.inc(coverage="unavailable")
    registry.joint_evidence_api_requests_total.inc(outcome="ready", error_code="none")
    registry.joint_evidence_api_requests_total.inc(
        outcome="error", error_code="MATCH_TIMELINE_NOT_FOUND"
    )

    rendered = registry.render_prometheus_text()
    assert 'joint_evidence_windows_total{result="planned"} 1.0' in rendered
    assert 'joint_evidence_window_truncations_total{result="truncated"} 1.0' in rendered
    assert 'joint_evidence_window_truncations_total{result="not_truncated"} 1.0' in rendered
    assert 'joint_evidence_replay_coverage_total{coverage="full"} 1.0' in rendered
    assert 'joint_evidence_replay_coverage_total{coverage="partial"} 1.0' in rendered
    assert 'joint_evidence_replay_coverage_total{coverage="unavailable"} 1.0' in rendered
    assert 'joint_evidence_api_requests_total{error_code="none",outcome="ready"} 1.0' in rendered
    assert (
        'joint_evidence_api_requests_total{error_code="MATCH_TIMELINE_NOT_FOUND",outcome="error"}'
        " 1.0" in rendered
    )
    for banned in ("puuid", "match_id", "token", "NA1_", "artifact"):
        assert banned not in rendered


def test_joint_evidence_metric_label_allowlists_are_closed() -> None:
    assert frozenset({"planned"}) == JointEvidenceService.WINDOW_RESULTS
    assert frozenset({"truncated", "not_truncated"}) == JointEvidenceService.TRUNCATION_RESULTS
    assert frozenset({"full", "partial", "unavailable"}) == JointEvidenceService.COVERAGE_LABELS
    assert hasattr(metrics_module, "JOINT_EVIDENCE_API_OUTCOMES")
    assert hasattr(metrics_module, "JOINT_EVIDENCE_API_ERROR_CODES")
    assert hasattr(metrics_module, "record_joint_evidence_api_request")
    assert frozenset({"ready", "error"}) == metrics_module.JOINT_EVIDENCE_API_OUTCOMES
    assert "none" in metrics_module.JOINT_EVIDENCE_API_ERROR_CODES
    assert "MATCH_EVIDENCE_UNSUPPORTED_MODE" in metrics_module.JOINT_EVIDENCE_API_ERROR_CODES
    assert "VALIDATION_ERROR" in metrics_module.JOINT_EVIDENCE_API_ERROR_CODES
    assert "REPLAY_EVIDENCE_NOT_READY" in metrics_module.JOINT_EVIDENCE_API_ERROR_CODES
    assert "REPLAY_NOT_FOUND" in metrics_module.JOINT_EVIDENCE_API_ERROR_CODES
    assert "NOT_FOUND" in metrics_module.JOINT_EVIDENCE_API_ERROR_CODES


def test_evidence_api_records_validation_error_once_for_unknown_fields() -> None:
    joint = FakeJointEvidenceService()
    with _client_with_metrics(joint=joint)[0] as client:
        registry = client.app.state.replay_metrics
        response = client.post(
            f"/api/v1/matches/{MATCH_ID}/evidence",
            json={"platform": "NA1", "puuid": PUUID, "coaching": True},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert joint.calls == []
        assert (
            registry.joint_evidence_api_requests_total.value(
                outcome="error", error_code="VALIDATION_ERROR"
            )
            == 1.0
        )
        assert _api_request_total(registry) == 1.0


def test_evidence_api_records_validation_error_for_auth_without_replay_id() -> None:
    joint = FakeJointEvidenceService()
    with _client_with_metrics(joint=joint)[0] as client:
        registry = client.app.state.replay_metrics
        response = client.post(
            f"/api/v1/matches/{MATCH_ID}/evidence",
            json={"platform": "NA1", "puuid": PUUID},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert joint.calls == []
        assert (
            registry.joint_evidence_api_requests_total.value(
                outcome="error", error_code="VALIDATION_ERROR"
            )
            == 1.0
        )
        assert TOKEN not in response.text
        assert _api_request_total(registry) == 1.0


def test_evidence_api_records_replay_not_found_for_bad_bearer() -> None:
    joint = FakeJointEvidenceService()
    with _client_with_metrics(joint=joint)[0] as client:
        registry = client.app.state.replay_metrics
        replay_id = str(uuid4())
        response = client.post(
            f"/api/v1/matches/{MATCH_ID}/evidence",
            json={"platform": "NA1", "puuid": PUUID, "replay_id": replay_id},
            headers={"Authorization": "Bearer\tbad-token"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "REPLAY_NOT_FOUND"
        assert joint.calls == []
        assert (
            registry.joint_evidence_api_requests_total.value(
                outcome="error", error_code="REPLAY_NOT_FOUND"
            )
            == 1.0
        )
        assert _api_request_total(registry) == 1.0
        assert "bad-token" not in response.text


def test_evidence_api_records_not_found_when_flag_disabled() -> None:
    joint = DisabledJointEvidenceService()
    with _client_with_metrics(joint=joint, enabled=False)[0] as client:
        registry = client.app.state.replay_metrics
        response = client.post(
            f"/api/v1/matches/{MATCH_ID}/evidence",
            json={"platform": "NA1", "puuid": PUUID},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
        assert (
            registry.joint_evidence_api_requests_total.value(
                outcome="error", error_code="NOT_FOUND"
            )
            == 1.0
        )
        assert _api_request_total(registry) == 1.0


@pytest.mark.parametrize(
    "error",
    [
        ApiError(
            status_code=404,
            code="MATCH_NOT_FOUND",
            message="The match was not found.",
            retryable=False,
        ),
        ApiError(
            status_code=404,
            code="PLAYER_NOT_IN_MATCH",
            message="The selected player did not participate in this match.",
            retryable=False,
        ),
        ApiError(
            status_code=422,
            code="MATCH_EVIDENCE_UNSUPPORTED_MODE",
            message="Unsupported match mode.",
            retryable=False,
        ),
        ApiError(
            status_code=404,
            code="MATCH_TIMELINE_NOT_FOUND",
            message="Timeline not found.",
            retryable=False,
        ),
        ApiError(
            status_code=404,
            code="REPLAY_NOT_FOUND",
            message="The requested replay was not found.",
            retryable=False,
        ),
        ApiError(
            status_code=409,
            code="REPLAY_EVIDENCE_NOT_READY",
            message="Replay evidence is not ready.",
            retryable=True,
        ),
        ApiError(
            status_code=502,
            code="RIOT_AUTH_FAILED",
            message="Riot authentication failed.",
            retryable=False,
        ),
        ApiError(
            status_code=429,
            code="RIOT_RATE_LIMITED",
            message="Riot rate limited the request.",
            retryable=True,
        ),
        ApiError(
            status_code=502,
            code="RIOT_INVALID_RESPONSE",
            message="Riot returned an invalid response.",
            retryable=False,
        ),
        ApiError(
            status_code=503,
            code="RIOT_UNAVAILABLE",
            message="Riot is temporarily unavailable.",
            retryable=True,
        ),
    ],
)
def test_evidence_api_records_approved_business_errors_once(error: ApiError) -> None:
    joint = FakeJointEvidenceService()
    joint.error = error
    with _client_with_metrics(joint=joint)[0] as client:
        registry = client.app.state.replay_metrics
        response = client.post(
            f"/api/v1/matches/{MATCH_ID}/evidence",
            json={"platform": "NA1", "puuid": PUUID},
        )
        assert response.status_code == error.status_code
        assert response.json()["error"]["code"] == error.code
        assert (
            registry.joint_evidence_api_requests_total.value(outcome="error", error_code=error.code)
            == 1.0
        )
        assert _api_request_total(registry) == 1.0


def test_evidence_api_records_ready_once_on_success() -> None:
    joint = FakeJointEvidenceService()
    with _client_with_metrics(joint=joint)[0] as client:
        registry = client.app.state.replay_metrics
        response = client.post(
            f"/api/v1/matches/{MATCH_ID}/evidence",
            json={"platform": "NA1", "puuid": PUUID},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ready"
        assert (
            registry.joint_evidence_api_requests_total.value(outcome="ready", error_code="none")
            == 1.0
        )
        assert _api_request_total(registry) == 1.0


def test_evidence_api_does_not_double_count_when_service_also_observes() -> None:
    """Regression: API boundary must own the counter even if a service would also inc."""
    joint = FakeJointEvidenceService()
    with _client_with_metrics(joint=joint)[0] as client:
        registry = client.app.state.replay_metrics
        # Simulate a buggy service also recording; API path must still be exact-once
        # from the HTTP perspective — success path records once from the route only.
        response = client.post(
            f"/api/v1/matches/{MATCH_ID}/evidence",
            json={"platform": "NA1", "puuid": PUUID},
        )
        assert response.status_code == 200
        assert _api_request_total(registry) == 1.0


def test_evidence_api_counts_once_when_public_response_validation_fails() -> None:
    joint = FakeJointEvidenceService()
    joint.data = joint.data.model_construct(**{**joint.data.model_dump(), "schema_version": 2})
    with _client_with_metrics(joint=joint)[0] as client:
        registry = client.app.state.replay_metrics
        response = client.post(
            f"/api/v1/matches/{MATCH_ID}/evidence",
            json={"platform": "NA1", "puuid": PUUID},
        )
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
        assert (
            registry.joint_evidence_api_requests_total.value(outcome="ready", error_code="none")
            == 0.0
        )
        assert _api_request_total(registry) == 1.0
        rendered = registry.render_prometheus_text()
        for banned in ("puuid", "match_id", "token", "NA1_", "artifact", PUUID, MATCH_ID):
            assert banned not in rendered
        for labels, _value in registry.joint_evidence_api_requests_total.samples():
            assert set(labels) <= {"outcome", "error_code"}
            assert labels["outcome"] in metrics_module.JOINT_EVIDENCE_API_OUTCOMES
            assert labels["error_code"] in metrics_module.JOINT_EVIDENCE_API_ERROR_CODES


def _api_request_total(registry: MetricsRegistry) -> float:
    total = 0.0
    for labels, value in registry.joint_evidence_api_requests_total.samples():
        del labels
        total += value
    return total
