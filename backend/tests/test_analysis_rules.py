from __future__ import annotations

from app.services.analyses.domain import (
    DIMENSION_ORDER,
    DimensionKey,
    DimensionScore,
    MetricEvidence,
    ScoreBreakdown,
)
from app.services.analyses.rules import RuleEngine
from app.services.analyses.rules_v1 import (
    GOAL_TARGETS,
    METRIC_VERSION,
    RULES_VERSION,
    SCORE_VERSION,
)

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


def _metric(key: str, value: float | None) -> MetricEvidence:
    available = value is not None
    return MetricEvidence(
        evidence_id=f"metric:v1:{key}",
        metric_key=key,
        category=_METRIC_CATEGORIES[key],
        status="available" if available else "unavailable",
        value=value,
        unit=_UNITS[key] if available else None,
        beneficial_direction="lower" if key == "deaths_per_10" else "higher",
        comparisons=(),
        confidence="high" if available else "low",
        source_type="match",
        source_fact_ids=(),
        unavailable_reason=None if available else "missing_match_value",
        metric_version=METRIC_VERSION,
    )


def _metrics(**values: float | None) -> tuple[MetricEvidence, ...]:
    defaults: dict[str, float | None] = {key: 1.0 for key in _METRIC_CATEGORIES}
    defaults.update(values)
    return tuple(_metric(key, value) for key, value in defaults.items())


def _dimension(
    dimension: DimensionKey,
    *,
    score: float | None,
    coverage: float = 1.0,
    evidence_ids: tuple[str, ...] | None = None,
) -> DimensionScore:
    default_ids = {
        "economy": ("metric:v1:cs_per_min", "metric:v1:gold_per_min"),
        "combat": ("metric:v1:kda", "metric:v1:damage_per_min"),
        "survivability": ("metric:v1:deaths_per_10",),
        "team_objectives": ("metric:v1:kill_participation", "metric:v1:explicit_objective_events"),
        "vision": ("metric:v1:vision_per_min",),
    }
    return DimensionScore(
        dimension=dimension,
        status="available" if score is not None else "unavailable",
        score=score,
        configured_weight=20,
        applied_weight=20 if score is not None else 0,
        coverage=coverage,
        evidence_ids=evidence_ids if evidence_ids is not None else default_ids[dimension],
    )


def _scores(
    *,
    role: str | None = "support",
    overall: float | None = 70.0,
    coverage: float = 1.0,
    dimension_scores: dict[DimensionKey, float | None] | None = None,
    dimension_coverage: dict[DimensionKey, float] | None = None,
    evidence_ids: dict[DimensionKey, tuple[str, ...]] | None = None,
) -> ScoreBreakdown:
    values = dimension_scores or {
        "economy": 50.0,
        "combat": 50.0,
        "survivability": 50.0,
        "team_objectives": 50.0,
        "vision": 50.0,
    }
    coverages = dimension_coverage or {}
    evidence = evidence_ids or {}
    return ScoreBreakdown(
        role=role,  # type: ignore[arg-type]
        dimensions=tuple(
            _dimension(
                dimension,
                score=values.get(dimension, 50.0),
                coverage=coverages.get(dimension, 1.0),
                evidence_ids=evidence.get(dimension),
            )
            for dimension in DIMENSION_ORDER
        ),
        overall_score=overall,
        coverage=coverage,
        score_version=SCORE_VERSION,
    )


def test_rule_engine_caps_findings_and_goals_and_closes_references() -> None:
    metrics = _metrics(
        cs_per_min=1.0,
        deaths_per_10=4.0,
        damage_per_min=100.0,
        kill_participation=0.2,
        vision_per_min=0.4,
    )
    scores = _scores(
        dimension_scores={
            "economy": 10.0,
            "combat": 15.0,
            "survivability": 80.0,
            "team_objectives": 20.0,
            "vision": 95.0,
        }
    )
    findings, goals = RuleEngine().evaluate(role="support", metrics=metrics, scores=scores)
    metric_ids = {item.evidence_id for item in metrics}
    assert len(findings) <= 3
    assert len(goals) <= 3
    assert all(ref in metric_ids for item in (*findings, *goals) for ref in item.evidence_ids)
    assert all(goal.rule_id != "goal.support.cs_per_min" for goal in goals)
    assert all(item.requires_replay_interpretation is False for item in findings)


def test_strength_and_improvement_thresholds_and_severity() -> None:
    scores = _scores(
        dimension_scores={
            "economy": 75.0,
            "combat": 90.0,
            "survivability": 50.0,
            "team_objectives": 20.0,
            "vision": 50.0,
        }
    )
    findings, _goals = RuleEngine().evaluate(role="mid", metrics=_metrics(), scores=scores)
    by_code = {item.message_code: item for item in findings}
    assert by_code["analysis.finding.economy.strength"].severity == "medium"
    assert by_code["analysis.finding.combat.strength"].severity == "high"
    assert by_code["analysis.finding.team_objectives.improvement"].severity == "high"
    assert "analysis.finding.vision.strength" not in by_code
    assert "analysis.finding.vision.improvement" not in by_code

    medium_improvement = _scores(
        dimension_scores={
            "economy": 50.0,
            "combat": 50.0,
            "survivability": 35.0,
            "team_objectives": 50.0,
            "vision": 50.0,
        }
    )
    findings, _goals = RuleEngine().evaluate(
        role="mid", metrics=_metrics(), scores=medium_improvement
    )
    assert findings[0].message_code == "analysis.finding.survivability.improvement"
    assert findings[0].severity == "medium"


def test_dimension_coverage_below_half_suppresses_findings() -> None:
    scores = _scores(
        dimension_scores={
            "economy": 100.0,
            "combat": 0.0,
            "survivability": 50.0,
            "team_objectives": 50.0,
            "vision": 50.0,
        },
        dimension_coverage={"economy": 0.49, "combat": 0.50},
    )
    findings, _goals = RuleEngine().evaluate(role="top", metrics=_metrics(), scores=scores)
    codes = {item.message_code for item in findings}
    assert "analysis.finding.economy.strength" not in codes
    assert "analysis.finding.combat.improvement" in codes


def test_unavailable_overall_score_suppresses_all_findings() -> None:
    scores = _scores(
        overall=None,
        coverage=0.5,
        dimension_scores={
            "economy": 100.0,
            "combat": 0.0,
            "survivability": 10.0,
            "team_objectives": 90.0,
            "vision": 5.0,
        },
    )
    findings, _goals = RuleEngine().evaluate(role="jungle", metrics=_metrics(), scores=scores)
    assert findings == ()


def test_finding_order_is_severity_kind_dimension_then_rule_id() -> None:
    scores = _scores(
        dimension_scores={
            "economy": 30.0,
            "combat": 10.0,
            "survivability": 80.0,
            "team_objectives": 35.0,
            "vision": 95.0,
        }
    )
    findings, _goals = RuleEngine().evaluate(role="bottom", metrics=_metrics(), scores=scores)
    assert [item.rule_id for item in findings] == [
        "finding.combat.improvement",
        "finding.vision.strength",
        "finding.economy.improvement",
    ]


def test_goals_use_each_role_target_and_omit_met_values() -> None:
    engine = RuleEngine()
    for role, targets in GOAL_TARGETS.items():
        values = {
            "cs_per_min": 0.1,
            "deaths_per_10": 0.5,
            "damage_per_min": 10.0,
            "kill_participation": 0.01,
            "vision_per_min": 0.01,
        }
        _findings, goals = engine.evaluate(
            role=role, metrics=_metrics(**values), scores=_scores(role=role)
        )
        by_key = {item.message_code.removeprefix("analysis.goal."): item for item in goals}
        if role == "support":
            assert "cs_per_min" not in by_key
        for metric_key, target in targets.items():
            if target is None or metric_key not in by_key:
                continue
            assert by_key[metric_key].target_value == target
            assert by_key[metric_key].role == role
            assert by_key[metric_key].rules_version == RULES_VERSION
        met_deaths = engine.evaluate(
            role=role,
            metrics=_metrics(
                deaths_per_10=2.0,
                cs_per_min=99.0,
                damage_per_min=999.0,
                kill_participation=1.0,
                vision_per_min=9.0,
            ),
            scores=_scores(role=role),
        )[1]
        assert all(goal.message_code != "analysis.goal.deaths_per_10" for goal in met_deaths)


def test_death_goals_are_lower_is_better_and_support_cs_is_never_emitted() -> None:
    findings, goals = RuleEngine().evaluate(
        role="support",
        metrics=_metrics(
            cs_per_min=0.1,
            deaths_per_10=5.0,
            damage_per_min=250.0,
            kill_participation=0.60,
            vision_per_min=1.20,
        ),
        scores=_scores(),
    )
    assert findings == ()
    codes = {item.message_code for item in goals}
    assert "analysis.goal.cs_per_min" not in codes
    assert "analysis.goal.deaths_per_10" in codes
    death_goal = next(item for item in goals if item.message_code == "analysis.goal.deaths_per_10")
    assert death_goal.current_value == 5.0
    assert death_goal.target_value == 2.0
    assert death_goal.rule_id == "goal.support.deaths_per_10"


def test_goals_order_by_normalized_gap_then_rule_id_and_cap_at_three() -> None:
    _findings, goals = RuleEngine().evaluate(
        role="mid",
        metrics=_metrics(
            cs_per_min=0.0,
            deaths_per_10=6.0,
            damage_per_min=0.0,
            kill_participation=0.0,
            vision_per_min=0.0,
        ),
        scores=_scores(role="mid"),
    )
    assert len(goals) == 3
    gaps = []
    for goal in goals:
        if goal.message_code == "analysis.goal.deaths_per_10":
            gaps.append((goal.current_value - goal.target_value) / goal.target_value)
        else:
            gaps.append((goal.target_value - goal.current_value) / goal.target_value)
    assert gaps == sorted(gaps, reverse=True)


def test_missing_metric_or_empty_evidence_is_suppressed() -> None:
    scores = _scores(
        dimension_scores={
            "economy": 10.0,
            "combat": 90.0,
            "survivability": 10.0,
            "team_objectives": 10.0,
            "vision": 10.0,
        },
        evidence_ids={"combat": ()},
    )
    metrics = _metrics(
        vision_per_min=None,
        deaths_per_10=None,
        cs_per_min=None,
        damage_per_min=None,
        kill_participation=None,
    )
    findings, goals = RuleEngine().evaluate(role="top", metrics=metrics, scores=scores)
    assert all(item.kind != "strength" or "combat" not in item.rule_id for item in findings)
    assert goals == ()
