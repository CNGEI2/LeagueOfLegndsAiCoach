from __future__ import annotations

import pytest

from app.services.analyses.domain import (
    DIMENSION_ORDER,
    DimensionKey,
    MetricComparison,
    MetricEvidence,
)
from app.services.analyses.rules_v1 import (
    METRIC_VERSION,
    OVERALL_COVERAGE_THRESHOLD,
    ROLE_WEIGHTS,
    SCORE_VERSION,
)
from app.services.analyses.scoring import ScoreEngine, meets_overall_threshold

_METRIC_CATEGORIES: dict[str, DimensionKey] = {
    "kda": "combat",
    "cs_per_min": "economy",
    "gold_per_min": "economy",
    "damage_per_min": "combat",
    "kill_participation": "combat",
    "deaths_per_10": "survivability",
    "vision_per_min": "vision",
    "explicit_objective_events": "team_objectives",
}
_UNITS = {
    "kda": "ratio",
    "cs_per_min": "per_minute",
    "gold_per_min": "per_minute",
    "damage_per_min": "per_minute",
    "kill_participation": "ratio",
    "deaths_per_10": "per_10_minutes",
    "vision_per_min": "per_minute",
    "explicit_objective_events": "count",
}


def _metric(
    key: str,
    *,
    team: float | None = None,
    same_role: float | None = None,
    value: float = 1.0,
) -> MetricEvidence:
    comparisons: list[MetricComparison] = []
    if team is not None:
        comparisons.append(MetricComparison(basis="team_percentile", score=team))
    if same_role is not None:
        comparisons.append(MetricComparison(basis="same_role", score=same_role, opponent_value=1.0))
    return MetricEvidence(
        evidence_id=f"metric:v1:{key}",
        metric_key=key,
        category=_METRIC_CATEGORIES[key],
        status="available",
        value=value,
        unit=_UNITS[key],
        beneficial_direction="lower" if key == "deaths_per_10" else "higher",
        comparisons=tuple(comparisons),
        confidence="high",
        source_type="timeline" if key == "explicit_objective_events" else "match",
        source_fact_ids=(),
        unavailable_reason=None,
        metric_version=METRIC_VERSION,
    )


def _unavailable(key: str) -> MetricEvidence:
    return MetricEvidence(
        evidence_id=f"metric:v1:{key}",
        metric_key=key,
        category=_METRIC_CATEGORIES[key],
        status="unavailable",
        value=None,
        unit=None,
        beneficial_direction="lower" if key == "deaths_per_10" else "higher",
        comparisons=(),
        confidence="low",
        source_type="match",
        source_fact_ids=(),
        unavailable_reason="missing_match_value",
        metric_version=METRIC_VERSION,
    )


def _full_metrics(*, team: float = 50.0, same_role: float = 50.0) -> tuple[MetricEvidence, ...]:
    return (
        _metric("kda", team=team),
        _metric("cs_per_min", team=team, same_role=same_role),
        _metric("gold_per_min", team=team, same_role=same_role),
        _metric("damage_per_min", team=team, same_role=same_role),
        _metric("kill_participation", team=team),
        _metric("deaths_per_10", team=team, same_role=same_role),
        _metric("vision_per_min", team=team, same_role=same_role),
        _metric("explicit_objective_events", team=team),
    )


def _support_exact_coverage_metrics() -> tuple[MetricEvidence, ...]:
    # Support raw weight 10+20+30=60 when economy, survivability, and vision are fully
    # available and combat/objectives contribute no signals (kill participation is shared).
    return (
        _metric("kda"),
        _metric("cs_per_min", team=80.0, same_role=40.0),
        _metric("gold_per_min", team=20.0, same_role=60.0),
        _metric("damage_per_min"),
        _metric("kill_participation"),
        _metric("deaths_per_10", team=10.0, same_role=90.0),
        _metric("vision_per_min", team=70.0, same_role=30.0),
        _metric("explicit_objective_events"),
    )


def test_score_engine_keeps_canonical_dimension_order_and_accepts_exact_coverage() -> None:
    scores = ScoreEngine().compute(role="support", metrics=_support_exact_coverage_metrics())
    assert [item.dimension for item in scores.dimensions] == list(DIMENSION_ORDER)
    assert scores.coverage == 0.60
    assert scores.overall_score is not None
    assert sum(item.applied_weight for item in scores.dimensions) == pytest.approx(100.0)
    assert scores.score_version == SCORE_VERSION


def test_coverage_threshold_accepts_0_60_and_rejects_0_5999() -> None:
    assert OVERALL_COVERAGE_THRESHOLD == 0.60
    assert meets_overall_threshold(0.60) is True
    assert meets_overall_threshold(0.5999) is False
    assert round(0.5999, 2) == 0.60


def test_below_threshold_coverage_suppresses_overall_and_applied_weights() -> None:
    metrics = (
        _metric("kda"),
        _unavailable("cs_per_min"),
        _unavailable("gold_per_min"),
        _metric("damage_per_min"),
        _metric("kill_participation"),
        _unavailable("deaths_per_10"),
        _metric("vision_per_min", team=100.0, same_role=100.0),
        _metric("explicit_objective_events"),
    )
    scores = ScoreEngine().compute(role="support", metrics=metrics)
    assert scores.coverage < OVERALL_COVERAGE_THRESHOLD
    assert scores.overall_score is None
    assert all(item.applied_weight == 0 for item in scores.dimensions)
    vision = next(item for item in scores.dimensions if item.dimension == "vision")
    assert vision.status == "available"
    assert vision.score == 100.0
    assert vision.configured_weight == 30


@pytest.mark.parametrize("role", ["top", "jungle", "mid", "bottom", "support"])
def test_role_weights_match_the_versioned_table(role: str) -> None:
    scores = ScoreEngine().compute(role=role, metrics=_full_metrics())  # type: ignore[arg-type]
    by_dimension = {item.dimension: item for item in scores.dimensions}
    for dimension, weight in ROLE_WEIGHTS[role].items():  # type: ignore[index]
        assert by_dimension[dimension].configured_weight == weight
        assert by_dimension[dimension].applied_weight == pytest.approx(float(weight))
        assert by_dimension[dimension].coverage == 1.0
    assert scores.coverage == 1.0
    assert scores.overall_score == 50.0


def test_dimension_score_renormalizes_over_available_signals_only() -> None:
    metrics = (
        _metric("kda"),
        _metric("cs_per_min", team=100.0),
        _metric("gold_per_min", team=0.0),
        _metric("damage_per_min"),
        _metric("kill_participation"),
        _metric("deaths_per_10"),
        _metric("vision_per_min"),
        _metric("explicit_objective_events"),
    )
    economy = next(
        item
        for item in ScoreEngine().compute(role="top", metrics=metrics).dimensions
        if item.dimension == "economy"
    )
    assert economy.coverage == 0.50
    assert economy.score == 50.0
    assert economy.evidence_ids == ("metric:v1:cs_per_min", "metric:v1:gold_per_min")


def test_unknown_role_has_dimension_scores_but_no_overall() -> None:
    scores = ScoreEngine().compute(role=None, metrics=_full_metrics(team=80.0, same_role=20.0))
    assert scores.role is None
    assert scores.overall_score is None
    assert scores.coverage == 0.0
    assert all(item.configured_weight == 0 for item in scores.dimensions)
    assert all(item.applied_weight == 0 for item in scores.dimensions)
    assert all(item.status == "available" and item.score is not None for item in scores.dimensions)


def test_scores_are_clamped_to_zero_one_hundred() -> None:
    scores = ScoreEngine().compute(role="mid", metrics=_full_metrics(team=0.0, same_role=100.0))
    assert scores.overall_score is not None
    assert 0 <= scores.overall_score <= 100
    for item in scores.dimensions:
        assert item.score is not None
        assert 0 <= item.score <= 100
        assert 0 <= item.applied_weight <= 100


def test_raw_metric_value_is_not_used_as_a_signal_score() -> None:
    metrics = (
        _metric("kda", value=99.0),
        _metric("cs_per_min", value=99.0),
        _metric("gold_per_min", value=99.0),
        _metric("damage_per_min", value=99.0),
        _metric("kill_participation", value=99.0),
        _metric("deaths_per_10", value=99.0),
        _metric("vision_per_min", value=99.0),
        _metric("explicit_objective_events", value=99.0),
    )
    scores = ScoreEngine().compute(role="support", metrics=metrics)
    assert all(item.status == "unavailable" and item.score is None for item in scores.dimensions)
    assert scores.overall_score is None


def test_win_loss_is_not_an_input_to_scoring() -> None:
    first = ScoreEngine().compute(role="jungle", metrics=_full_metrics(team=40.0, same_role=60.0))
    second = ScoreEngine().compute(role="jungle", metrics=_full_metrics(team=40.0, same_role=60.0))
    assert first == second
    assert "won" not in ScoreEngine.compute.__code__.co_varnames


def test_property_scores_stay_within_bounds_across_roles_and_signals() -> None:
    engine = ScoreEngine()
    for role in ROLE_WEIGHTS:
        for team in (0.0, 33.33, 50.0, 66.67, 100.0):
            for same_role in (0.0, 50.0, 100.0):
                scores = engine.compute(
                    role=role, metrics=_full_metrics(team=team, same_role=same_role)
                )
                assert scores.overall_score is not None
                assert 0 <= scores.overall_score <= 100
                assert 0 <= scores.coverage <= 1
                for item in scores.dimensions:
                    assert item.score is not None
                    assert 0 <= item.score <= 100
                    assert 0 <= item.coverage <= 1
                    assert 0 <= item.applied_weight <= 100
