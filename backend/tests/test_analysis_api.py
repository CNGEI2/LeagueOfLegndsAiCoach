from __future__ import annotations

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dependencies import AppServices
from app.core.errors import ApiError
from app.core.routing import Platform
from app.main import create_app
from app.services.analyses.domain import (
    DeterministicAnalysisResult,
    DimensionScore,
    Finding,
    MetricComparison,
    MetricEvidence,
    ScoreBreakdown,
    TrainingGoal,
)
from app.services.analyses.service import DisabledAnalysisService
from tests.conftest import (
    FakeDatabase,
    FakeMatchService,
    FakePlatformDetectionService,
    FakePlayerService,
    FakeReplayService,
)

SECRET_PUUID = "secret-selected-puuid-xyz"
ANALYSIS_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
MATCH_ID = "NA1_ANALYSIS_FIXTURE"
EVIDENCE_ID = "metric:v1:kda"


def _metric() -> MetricEvidence:
    return MetricEvidence(
        evidence_id=EVIDENCE_ID,
        metric_key="kda",
        category="combat",
        status="available",
        value=6.0,
        unit="ratio",
        beneficial_direction="higher",
        comparisons=(MetricComparison(basis="team_percentile", score=50.0),),
        confidence="high",
        source_type="match",
        source_fact_ids=(),
        unavailable_reason=None,
        metric_version="deterministic-metrics-v1",
    )


def _result() -> DeterministicAnalysisResult:
    return DeterministicAnalysisResult(
        status="completed",
        platform=Platform.NA1,
        match_id=MATCH_ID,
        selected_puuid=SECRET_PUUID,
        role="support",
        metrics=(_metric(),),
        scores=ScoreBreakdown(
            role="support",
            dimensions=tuple(
                DimensionScore(
                    dimension=dimension,
                    status="available",
                    score=50.0,
                    configured_weight=20.0,
                    applied_weight=20.0,
                    coverage=1.0,
                    evidence_ids=(EVIDENCE_ID,),
                )
                for dimension in (
                    "economy",
                    "combat",
                    "survivability",
                    "team_objectives",
                    "vision",
                )
            ),
            overall_score=50.0,
            coverage=1.0,
            score_version="deterministic-score-v1",
        ),
        findings=(
            Finding(
                rule_id="finding.vision.strength",
                kind="strength",
                severity="medium",
                message_code="analysis.finding.vision.strength",
                params={"score": 80.0},
                evidence_ids=(EVIDENCE_ID,),
                confidence="medium",
                requires_replay_interpretation=False,
            ),
        ),
        goals=(
            TrainingGoal(
                rule_id="goal.support.vision_per_min",
                message_code="analysis.goal.vision_per_min",
                current_value=0.8,
                target_value=1.2,
                unit="per_minute",
                role="support",
                evidence_ids=(EVIDENCE_ID,),
                rules_version="deterministic-rules-v1",
            ),
        ),
        unavailable_reasons=(),
        input_hash="a" * 64,
        metric_version="deterministic-metrics-v1",
        score_version="deterministic-score-v1",
        rules_version="deterministic-rules-v1",
        schema_version=1,
    )


class RecordingAnalysisService:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []
        self.error: ApiError | None = None
        self.created = True
        self.analysis_id = ANALYSIS_ID
        self.result = _result()

    async def create_or_reuse(
        self, *, platform: Platform, match_id: str, puuid: str
    ) -> tuple[UUID, DeterministicAnalysisResult, bool]:
        self.create_calls.append({"platform": platform, "match_id": match_id, "puuid": puuid})
        if self.error is not None:
            raise self.error
        return self.analysis_id, self.result, self.created

    async def get(self, *, analysis_id: UUID) -> DeterministicAnalysisResult:
        self.get_calls.append({"analysis_id": analysis_id})
        if self.error is not None:
            raise self.error
        return self.result


def _settings(*, enabled: bool) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        riot_api_key="RGAPI-test",
        joint_evidence_enabled=enabled,
        deterministic_analysis_enabled=enabled,
    )


def _services(analysis: object) -> AppServices:
    return AppServices(
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=FakePlatformDetectionService(),
        closers=(),
        analysis_service=analysis,  # type: ignore[arg-type]
    )


@pytest.fixture
def analysis_client() -> Generator[tuple[TestClient, RecordingAnalysisService], None, None]:
    analysis = RecordingAnalysisService()
    application = create_app(
        settings=_settings(enabled=True),
        database=FakeDatabase(),
        services=_services(analysis),
    )
    with TestClient(application) as client:
        yield client, analysis


@pytest.fixture
def disabled_client() -> Generator[TestClient, None, None]:
    application = create_app(
        settings=_settings(enabled=False),
        database=FakeDatabase(),
        services=_services(DisabledAnalysisService()),
    )
    with TestClient(application) as client:
        yield client


def _assert_private(body: str) -> None:
    assert SECRET_PUUID not in body
    assert "selected_puuid" not in body
    assert "replay_token" not in body
    assert "capability-token" not in body
    assert "detail" not in body or '"error"' in body


def test_disabled_create_and_get_are_dark_404(disabled_client: TestClient) -> None:
    created = disabled_client.post(
        "/api/v1/analyses",
        json={"platform": "NA1", "match_id": MATCH_ID, "puuid": "player-1"},
    )
    loaded = disabled_client.get(f"/api/v1/analyses/{ANALYSIS_ID}")
    for response in (created, loaded):
        assert response.status_code == 404
        payload = response.json()
        assert payload["error"]["code"] == "NOT_FOUND"
        assert payload["error"]["message"] == "The requested resource was not found."
        assert payload["error"]["retryable"] is False
        assert payload["error"]["request_id"] == response.headers["X-Request-ID"]
        _assert_private(response.text)


def test_create_validates_body_calls_service_without_locale_and_echoes_locale(
    analysis_client: tuple[TestClient, RecordingAnalysisService],
) -> None:
    client, analysis = analysis_client
    invalid = client.post(
        "/api/v1/analyses",
        json={"platform": "NA1", "match_id": MATCH_ID, "puuid": "player-1", "coaching": True},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    assert analysis.create_calls == []

    response = client.post(
        "/api/v1/analyses",
        json={
            "platform": "NA1",
            "match_id": MATCH_ID,
            "puuid": "player-1",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["locale"] == "zh-CN"
    assert body["cached"] is False
    assert body["analysis_id"] == str(ANALYSIS_ID)
    assert body["scope_notice_code"] == "DETERMINISTIC_DATA_COACHING_NO_AI"
    assert body["role"] == "support"
    assert analysis.create_calls == [
        {"platform": Platform.NA1, "match_id": MATCH_ID, "puuid": "player-1"}
    ]
    _assert_private(response.text)


def test_create_returns_cached_true_on_reuse(
    analysis_client: tuple[TestClient, RecordingAnalysisService],
) -> None:
    client, analysis = analysis_client
    analysis.created = False
    response = client.post(
        "/api/v1/analyses",
        json={"platform": "NA1", "match_id": MATCH_ID, "puuid": "player-1"},
    )
    assert response.status_code == 200
    assert response.json()["cached"] is True
    assert response.json()["locale"] == "en-US"


def test_get_requires_supported_locale_and_returns_cached_true(
    analysis_client: tuple[TestClient, RecordingAnalysisService],
) -> None:
    client, analysis = analysis_client
    invalid = client.get(f"/api/v1/analyses/{ANALYSIS_ID}", params={"locale": "en-GB"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    assert analysis.get_calls == []

    response = client.get(f"/api/v1/analyses/{ANALYSIS_ID}", params={"locale": "zh-CN"})
    assert response.status_code == 200
    body = response.json()
    assert body["cached"] is True
    assert body["locale"] == "zh-CN"
    assert analysis.get_calls == [{"analysis_id": ANALYSIS_ID}]
    _assert_private(response.text)


def test_unknown_analysis_id_returns_safe_404(
    analysis_client: tuple[TestClient, RecordingAnalysisService],
) -> None:
    client, analysis = analysis_client
    analysis.error = ApiError(
        status_code=404,
        code="NOT_FOUND",
        message="The requested resource was not found.",
        retryable=False,
    )
    response = client.get(f"/api/v1/analyses/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    _assert_private(response.text)


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        ("MATCH_ANALYSIS_UNSUPPORTED_MODE", 422),
        ("PLAYER_NOT_IN_MATCH", 404),
        ("RIOT_INVALID_RESPONSE", 502),
    ],
)
def test_create_preserves_allowlisted_errors(
    analysis_client: tuple[TestClient, RecordingAnalysisService],
    code: str,
    status_code: int,
) -> None:
    client, analysis = analysis_client
    analysis.error = ApiError(
        status_code=status_code,
        code=code,
        message=code,
        retryable=False,
    )
    response = client.post(
        "/api/v1/analyses",
        json={"platform": "NA1", "match_id": MATCH_ID, "puuid": "player-1"},
    )
    assert response.status_code == status_code
    payload = response.json()
    assert payload["error"]["code"] == code
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message", "params", "retryable", "request_id"}
    _assert_private(response.text)
