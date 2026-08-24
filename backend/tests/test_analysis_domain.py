from types import MappingProxyType

import pytest
from pydantic import ValidationError

from app.core.routing import Platform
from app.services.analyses.domain import (
    DeterministicAnalysisResult,
    DimensionScore,
    Finding,
    MetricComparison,
    MetricEvidence,
    ScoreBreakdown,
    TrainingGoal,
    normalize_analysis_role,
)
from app.services.analyses.rules_v1 import (
    DIMENSION_PRIORITIES,
    DIMENSION_SIGNALS,
    FINDING_IMPROVEMENT_HIGH_MAX,
    FINDING_IMPROVEMENT_MAX,
    FINDING_KIND_ORDER,
    FINDING_STRENGTH_HIGH_MIN,
    FINDING_STRENGTH_MIN,
    GOAL_TARGETS,
    MAX_FINDINGS,
    MAX_GOALS,
    METRIC_VERSION,
    MIN_DIMENSION_COVERAGE_FOR_FINDING,
    OVERALL_COVERAGE_THRESHOLD,
    RESULT_SCHEMA_VERSION,
    ROLE_WEIGHTS,
    RULES_VERSION,
    SCORE_VERSION,
    SEVERITY_ORDER,
)


@pytest.mark.parametrize(
    ("upstream", "expected"),
    [
        ("TOP", "top"),
        ("JUNGLE", "jungle"),
        ("MIDDLE", "mid"),
        ("BOTTOM", "bottom"),
        ("UTILITY", "support"),
        (None, None),
        ("", None),
    ],
)
def test_normalize_analysis_role(upstream: str | None, expected: str | None) -> None:
    assert normalize_analysis_role(upstream) == expected


def test_normalize_analysis_role_rejects_unknown_and_product_terms() -> None:
    assert normalize_analysis_role("SUPPORT") is None
    assert normalize_analysis_role("utility") is None
    assert normalize_analysis_role("ADC") is None


def _comparison(*, basis: str = "team_percentile", score: float = 50.0) -> MetricComparison:
    return MetricComparison(basis=basis, score=score, opponent_value=None)


def _available_metric(*, evidence_id: str = "metric:v1:kda") -> MetricEvidence:
    return MetricEvidence(
        evidence_id=evidence_id,
        metric_key="kda",
        category="combat",
        status="available",
        value=6.0,
        unit="ratio",
        beneficial_direction="higher",
        comparisons=(_comparison(),),
        confidence="high",
        source_type="match",
        source_fact_ids=(),
        unavailable_reason=None,
        metric_version="deterministic-metrics-v1",
    )


def _unavailable_metric() -> MetricEvidence:
    return MetricEvidence(
        evidence_id="metric:v1:explicit_objective_events",
        metric_key="explicit_objective_events",
        category="team_objectives",
        status="unavailable",
        value=None,
        unit=None,
        beneficial_direction="higher",
        comparisons=(),
        confidence="low",
        source_type="timeline",
        source_fact_ids=(),
        unavailable_reason="timeline_unavailable",
        metric_version="deterministic-metrics-v1",
    )


def _dimension(
    *,
    dimension: str,
    configured_weight: float = 20.0,
    applied_weight: float = 20.0,
    coverage: float = 1.0,
    score: float | None = 50.0,
    status: str = "available",
) -> DimensionScore:
    return DimensionScore(
        dimension=dimension,
        status=status,
        score=score,
        configured_weight=configured_weight,
        applied_weight=applied_weight,
        coverage=coverage,
        evidence_ids=("metric:v1:kda",),
    )


def _dimensions() -> tuple[DimensionScore, ...]:
    return (
        _dimension(dimension="economy"),
        _dimension(dimension="combat"),
        _dimension(dimension="survivability"),
        _dimension(dimension="team_objectives"),
        _dimension(dimension="vision"),
    )


def _scores() -> ScoreBreakdown:
    return ScoreBreakdown(
        role="support",
        dimensions=_dimensions(),
        overall_score=50.0,
        coverage=1.0,
        score_version="deterministic-score-v1",
    )


def _finding() -> Finding:
    return Finding(
        rule_id="finding.vision.strength",
        kind="strength",
        severity="medium",
        message_code="analysis.finding.vision.strength",
        params={"score": 80.0, "coverage": 1.0},
        evidence_ids=("metric:v1:kda",),
        confidence="medium",
        requires_replay_interpretation=False,
    )


def _goal() -> TrainingGoal:
    return TrainingGoal(
        rule_id="goal.support.vision_per_min",
        message_code="analysis.goal.vision_per_min",
        current_value=0.8,
        target_value=1.2,
        unit="per_minute",
        role="support",
        evidence_ids=("metric:v1:kda",),
        rules_version="deterministic-rules-v1",
    )


def _result() -> DeterministicAnalysisResult:
    return DeterministicAnalysisResult(
        status="completed",
        platform=Platform.NA1,
        match_id="NA1_123",
        selected_puuid="selected",
        role="support",
        metrics=(_available_metric(),),
        scores=_scores(),
        findings=(_finding(),),
        goals=(_goal(),),
        unavailable_reasons=(),
        input_hash="a" * 64,
        metric_version="deterministic-metrics-v1",
        score_version="deterministic-score-v1",
        rules_version="deterministic-rules-v1",
        schema_version=1,
    )


def test_metric_evidence_rejects_available_without_value_or_unit() -> None:
    with pytest.raises(ValidationError):
        MetricEvidence(
            evidence_id="metric:v1:kda",
            metric_key="kda",
            category="combat",
            status="available",
            value=None,
            unit="ratio",
            beneficial_direction="higher",
            comparisons=(),
            confidence="high",
            source_type="match",
            source_fact_ids=(),
            unavailable_reason=None,
            metric_version="deterministic-metrics-v1",
        )
    with pytest.raises(ValidationError):
        MetricEvidence(
            evidence_id="metric:v1:kda",
            metric_key="kda",
            category="combat",
            status="available",
            value=6.0,
            unit=None,
            beneficial_direction="higher",
            comparisons=(),
            confidence="high",
            source_type="match",
            source_fact_ids=(),
            unavailable_reason=None,
            metric_version="deterministic-metrics-v1",
        )


def test_metric_evidence_rejects_unavailable_with_a_value() -> None:
    with pytest.raises(ValidationError):
        MetricEvidence(
            evidence_id="metric:v1:kda",
            metric_key="kda",
            category="combat",
            status="unavailable",
            value=0.0,
            unit=None,
            beneficial_direction="higher",
            comparisons=(),
            confidence="low",
            source_type="match",
            source_fact_ids=(),
            unavailable_reason="missing_match_value",
            metric_version="deterministic-metrics-v1",
        )


def test_metric_comparison_rejects_scores_outside_bounds() -> None:
    with pytest.raises(ValidationError):
        MetricComparison(basis="team_percentile", score=-0.01)
    with pytest.raises(ValidationError):
        MetricComparison(basis="team_percentile", score=100.01)


def test_metric_evidence_rejects_duplicate_comparison_bases() -> None:
    payload = _available_metric().model_dump(mode="json")
    payload["comparisons"].append(payload["comparisons"][0])
    with pytest.raises(ValidationError):
        MetricEvidence.model_validate(payload)


def test_dimension_score_rejects_negative_weights_and_out_of_range_scores() -> None:
    with pytest.raises(ValidationError):
        _dimension(dimension="economy", configured_weight=-1)
    with pytest.raises(ValidationError):
        _dimension(dimension="economy", applied_weight=-1)
    with pytest.raises(ValidationError):
        _dimension(dimension="economy", score=100.01)
    with pytest.raises(ValidationError):
        _dimension(dimension="economy", score=-0.01)
    with pytest.raises(ValidationError):
        _dimension(dimension="economy", coverage=1.01)


def test_dimension_score_rejects_broken_availability_shape() -> None:
    with pytest.raises(ValidationError):
        _dimension(dimension="economy", status="available", score=None)
    with pytest.raises(ValidationError):
        _dimension(dimension="economy", status="unavailable", score=50.0)


def test_score_breakdown_requires_five_unique_ordered_dimensions() -> None:
    valid = _scores()
    assert [item.dimension for item in valid.dimensions] == [
        "economy",
        "combat",
        "survivability",
        "team_objectives",
        "vision",
    ]
    with pytest.raises(ValidationError):
        ScoreBreakdown(
            role="support",
            dimensions=valid.dimensions[:4],
            overall_score=50.0,
            coverage=1.0,
            score_version="deterministic-score-v1",
        )
    shuffled = (
        valid.dimensions[1],
        valid.dimensions[0],
        valid.dimensions[2],
        valid.dimensions[3],
        valid.dimensions[4],
    )
    with pytest.raises(ValidationError):
        ScoreBreakdown(
            role="support",
            dimensions=shuffled,
            overall_score=50.0,
            coverage=1.0,
            score_version="deterministic-score-v1",
        )


def test_score_breakdown_rejects_overall_score_outside_bounds() -> None:
    with pytest.raises(ValidationError):
        ScoreBreakdown(
            role="support",
            dimensions=_dimensions(),
            overall_score=100.01,
            coverage=1.0,
            score_version="deterministic-score-v1",
        )


@pytest.mark.parametrize(
    ("role", "coverage"),
    [
        (None, 1.0),
        ("support", OVERALL_COVERAGE_THRESHOLD - 0.0001),
    ],
)
def test_score_breakdown_rejects_overall_without_role_or_coverage(
    role: str | None,
    coverage: float,
) -> None:
    with pytest.raises(ValidationError):
        ScoreBreakdown(
            role=role,
            dimensions=_dimensions(),
            overall_score=50.0,
            coverage=coverage,
            score_version="deterministic-score-v1",
        )


def test_finding_and_goal_reject_broken_status_shapes() -> None:
    with pytest.raises(ValidationError):
        Finding(
            rule_id="finding.vision.strength",
            kind="weakness",  # type: ignore[arg-type]
            severity="medium",
            message_code="analysis.finding.vision.strength",
            params={},
            evidence_ids=("metric:v1:kda",),
            confidence="medium",
        )
    with pytest.raises(ValidationError):
        TrainingGoal(
            rule_id="goal.support.vision_per_min",
            message_code="analysis.goal.vision_per_min",
            current_value=0.8,
            target_value=1.2,
            unit="per_minute",
            role="utility",  # type: ignore[arg-type]
            evidence_ids=("metric:v1:kda",),
            rules_version="deterministic-rules-v1",
        )


def test_result_rejects_broken_status_and_extra_locale_or_replay_fields() -> None:
    with pytest.raises(ValidationError):
        DeterministicAnalysisResult(
            status="failed",  # type: ignore[arg-type]
            platform=Platform.NA1,
            match_id="NA1_123",
            selected_puuid="selected",
            role="support",
            metrics=(_available_metric(),),
            scores=_scores(),
            findings=(),
            goals=(),
            unavailable_reasons=(),
            input_hash="a" * 64,
            metric_version="deterministic-metrics-v1",
            score_version="deterministic-score-v1",
            rules_version="deterministic-rules-v1",
            schema_version=1,
        )
    with pytest.raises(ValidationError):
        DeterministicAnalysisResult(
            **_result().model_dump(),
            locale="zh-CN",
        )
    with pytest.raises(ValidationError):
        DeterministicAnalysisResult(
            **_result().model_dump(),
            replay_id="replay-1",
        )


def test_valid_models_round_trip() -> None:
    result = _result()
    restored = DeterministicAnalysisResult.model_validate(result.model_dump(mode="json"))
    assert restored == result
    assert restored.role == "support"
    assert _unavailable_metric().status == "unavailable"


def test_result_rejects_cross_field_integrity_drift() -> None:
    duplicate_metrics = _result().model_dump(mode="json")
    duplicate_metrics["metrics"].append(duplicate_metrics["metrics"][0])
    with pytest.raises(ValidationError):
        DeterministicAnalysisResult.model_validate(duplicate_metrics)

    missing_dimension_reference = _result().model_dump(mode="json")
    missing_dimension_reference["scores"]["dimensions"][0]["evidence_ids"] = ["missing"]
    with pytest.raises(ValidationError):
        DeterministicAnalysisResult.model_validate(missing_dimension_reference)

    role_drift = _result().model_dump(mode="json")
    role_drift["scores"]["role"] = "top"
    with pytest.raises(ValidationError):
        DeterministicAnalysisResult.model_validate(role_drift)

    metric_version_drift = _result().model_dump(mode="json")
    metric_version_drift["metrics"][0]["metric_version"] = "other-metric-version"
    with pytest.raises(ValidationError):
        DeterministicAnalysisResult.model_validate(metric_version_drift)

    score_version_drift = _result().model_dump(mode="json")
    score_version_drift["scores"]["score_version"] = "other-score-version"
    with pytest.raises(ValidationError):
        DeterministicAnalysisResult.model_validate(score_version_drift)

    goal_drift = _result().model_dump(mode="json")
    goal_drift["goals"][0]["role"] = "top"
    goal_drift["goals"][0]["rules_version"] = "other-rules-version"
    with pytest.raises(ValidationError):
        DeterministicAnalysisResult.model_validate(goal_drift)

    unavailable_score_status_drift = _result().model_dump(mode="json")
    unavailable_score_status_drift["role"] = None
    unavailable_score_status_drift["scores"]["role"] = None
    unavailable_score_status_drift["scores"]["overall_score"] = None
    with pytest.raises(ValidationError):
        DeterministicAnalysisResult.model_validate(unavailable_score_status_drift)

    unavailable_score_finding_drift = _result().model_dump(mode="json")
    unavailable_score_finding_drift["status"] = "partial"
    unavailable_score_finding_drift["scores"]["coverage"] = OVERALL_COVERAGE_THRESHOLD - 0.0001
    unavailable_score_finding_drift["scores"]["overall_score"] = None
    with pytest.raises(ValidationError):
        DeterministicAnalysisResult.model_validate(unavailable_score_finding_drift)


def test_ruleset_constants_are_immutable_and_match_v1() -> None:
    assert METRIC_VERSION == "deterministic-metrics-v1"
    assert SCORE_VERSION == "deterministic-score-v1"
    assert RULES_VERSION == "deterministic-rules-v1"
    assert RESULT_SCHEMA_VERSION == 1
    assert OVERALL_COVERAGE_THRESHOLD == 0.60
    assert FINDING_STRENGTH_MIN == 75
    assert FINDING_STRENGTH_HIGH_MIN == 90
    assert FINDING_IMPROVEMENT_MAX == 35
    assert FINDING_IMPROVEMENT_HIGH_MAX == 20
    assert MIN_DIMENSION_COVERAGE_FOR_FINDING == 0.50
    assert MAX_FINDINGS == 3
    assert MAX_GOALS == 3
    assert SEVERITY_ORDER == ("high", "medium", "low")
    assert FINDING_KIND_ORDER == ("improvement", "strength")
    assert DIMENSION_PRIORITIES == {
        "economy": 10,
        "combat": 20,
        "survivability": 30,
        "team_objectives": 40,
        "vision": 50,
    }
    assert ROLE_WEIGHTS == {
        "top": {
            "economy": 25,
            "combat": 25,
            "survivability": 20,
            "team_objectives": 15,
            "vision": 15,
        },
        "mid": {
            "economy": 25,
            "combat": 25,
            "survivability": 20,
            "team_objectives": 15,
            "vision": 15,
        },
        "bottom": {
            "economy": 25,
            "combat": 25,
            "survivability": 20,
            "team_objectives": 15,
            "vision": 15,
        },
        "jungle": {
            "economy": 20,
            "combat": 20,
            "survivability": 20,
            "team_objectives": 25,
            "vision": 15,
        },
        "support": {
            "economy": 10,
            "combat": 20,
            "survivability": 20,
            "team_objectives": 20,
            "vision": 30,
        },
    }
    assert DIMENSION_SIGNALS == {
        "economy": {
            "cs_per_min_team": 25,
            "gold_per_min_team": 25,
            "cs_per_min_same_role": 25,
            "gold_per_min_same_role": 25,
        },
        "combat": {
            "kda_team": 20,
            "kill_participation_team": 20,
            "damage_per_min_team": 30,
            "damage_per_min_same_role": 30,
        },
        "survivability": {
            "deaths_per_10_team": 50,
            "deaths_per_10_same_role": 50,
        },
        "team_objectives": {
            "kill_participation_team": 60,
            "explicit_objective_events_team": 40,
        },
        "vision": {
            "vision_per_min_team": 70,
            "vision_per_min_same_role": 30,
        },
    }
    assert GOAL_TARGETS["support"]["cs_per_min"] is None
    assert GOAL_TARGETS["support"]["vision_per_min"] == 1.20
    assert isinstance(ROLE_WEIGHTS, MappingProxyType)
    assert isinstance(DIMENSION_SIGNALS, MappingProxyType)
    assert isinstance(GOAL_TARGETS, MappingProxyType)
    with pytest.raises(TypeError):
        ROLE_WEIGHTS["support"] = {"economy": 99}  # type: ignore[index]
    with pytest.raises((TypeError, AttributeError)):
        ROLE_WEIGHTS["support"]["economy"] = 99  # type: ignore[index]
