from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.routing import Platform
from app.schemas.analyses import AnalysisCreateRequest, AnalysisResponse
from app.schemas.domain import Locale
from app.services.analyses.domain import (
    DimensionScore,
    Finding,
    MetricComparison,
    MetricEvidence,
    ScoreBreakdown,
    TrainingGoal,
)

ANALYSIS_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
INPUT_HASH = "a" * 64
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


def _dimensions() -> tuple[DimensionScore, ...]:
    return tuple(
        DimensionScore(
            dimension=dimension,
            status="available",
            score=50.0,
            configured_weight=20.0,
            applied_weight=20.0,
            coverage=1.0,
            evidence_ids=(EVIDENCE_ID,),
        )
        for dimension in ("economy", "combat", "survivability", "team_objectives", "vision")
    )


def _finding(*, evidence_ids: tuple[str, ...] = (EVIDENCE_ID,)) -> Finding:
    return Finding(
        rule_id="finding.vision.strength",
        kind="strength",
        severity="medium",
        message_code="analysis.finding.vision.strength",
        params={"score": 80.0},
        evidence_ids=evidence_ids,
        confidence="medium",
        requires_replay_interpretation=False,
    )


def _goal(*, evidence_ids: tuple[str, ...] = (EVIDENCE_ID,)) -> TrainingGoal:
    return TrainingGoal(
        rule_id="goal.support.vision_per_min",
        message_code="analysis.goal.vision_per_min",
        current_value=0.8,
        target_value=1.2,
        unit="per_minute",
        role="support",
        evidence_ids=evidence_ids,
        rules_version="deterministic-rules-v1",
    )


def _response_kwargs(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "analysis_id": ANALYSIS_ID,
        "status": "completed",
        "cached": False,
        "locale": Locale.EN_US,
        "role": "support",
        "metrics": (_metric(),),
        "scores": ScoreBreakdown(
            role="support",
            dimensions=_dimensions(),
            overall_score=50.0,
            coverage=1.0,
            score_version="deterministic-score-v1",
        ),
        "findings": (_finding(),),
        "goals": (_goal(),),
        "unavailable_reasons": (),
        "input_hash": INPUT_HASH,
        "metric_version": "deterministic-metrics-v1",
        "score_version": "deterministic-score-v1",
        "rules_version": "deterministic-rules-v1",
        "schema_version": 1,
        "scope_notice_code": "DETERMINISTIC_DATA_COACHING_NO_AI",
        "request_id": "req-1",
    }
    payload.update(overrides)
    return payload


def test_create_request_accepts_supported_locales_and_rejects_extras() -> None:
    for locale in (Locale.EN_US, Locale.ZH_CN):
        request = AnalysisCreateRequest(
            platform=Platform.NA1,
            match_id="NA1_1",
            puuid="player-1",
            locale=locale,
        )
        assert request.locale is locale
    with pytest.raises(ValidationError):
        AnalysisCreateRequest(
            platform=Platform.NA1,
            match_id="NA1_1",
            puuid="player-1",
            locale="en-GB",  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnalysisCreateRequest(
            platform=Platform.NA1,
            match_id="NA1_1",
            puuid="player-1",
            coaching=True,  # type: ignore[call-arg]
        )


def test_create_request_rejects_oversized_identifiers() -> None:
    with pytest.raises(ValidationError):
        AnalysisCreateRequest(platform=Platform.NA1, match_id="x" * 65, puuid="player-1")
    with pytest.raises(ValidationError):
        AnalysisCreateRequest(platform=Platform.NA1, match_id="NA1_1", puuid="p" * 129)
    with pytest.raises(ValidationError):
        AnalysisCreateRequest(platform=Platform.NA1, match_id="", puuid="player-1")


def test_response_accepts_completed_payload_without_selected_puuid() -> None:
    response = AnalysisResponse(**_response_kwargs())
    dumped = response.model_dump(mode="json")
    assert "selected_puuid" not in dumped
    assert dumped["scope_notice_code"] == "DETERMINISTIC_DATA_COACHING_NO_AI"
    assert dumped["schema_version"] == 1
    assert dumped["role"] == "support"


def test_response_rejects_extra_fields_and_selected_puuid() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnalysisResponse(**_response_kwargs(), selected_puuid="secret-selected-puuid")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnalysisResponse(**_response_kwargs(), match_id="NA1_123")


def test_response_rejects_unsupported_locale_role_and_status() -> None:
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(locale="en-GB"))
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(role="UTILITY"))
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(role="utility"))
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(status="failed"))


def test_response_rejects_malformed_uuid_and_hash() -> None:
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(analysis_id="not-a-uuid"))
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(input_hash="A" * 64))
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(input_hash="a" * 63))
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(schema_version=2))
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(scope_notice_code="DATA_ONLY_NO_COACHING"))


def test_response_rejects_invalid_evidence_references() -> None:
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(findings=(_finding(evidence_ids=("missing",)),)))
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(goals=(_goal(evidence_ids=("missing",)),)))


def test_response_rejects_more_than_three_findings_or_goals() -> None:
    findings = tuple(_finding() for _ in range(4))
    goals = tuple(_goal() for _ in range(4))
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(findings=findings))
    with pytest.raises(ValidationError):
        AnalysisResponse(**_response_kwargs(goals=goals))
