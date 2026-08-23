from __future__ import annotations

from typing import Literal

from app.services.analyses.domain import (
    AnalysisRole,
    DimensionKey,
    Finding,
    MetricEvidence,
    ScoreBreakdown,
    TrainingGoal,
)
from app.services.analyses.rules_v1 import (
    DIMENSION_PRIORITIES,
    FINDING_IMPROVEMENT_HIGH_MAX,
    FINDING_IMPROVEMENT_MAX,
    FINDING_KIND_ORDER,
    FINDING_STRENGTH_HIGH_MIN,
    FINDING_STRENGTH_MIN,
    GOAL_TARGETS,
    MAX_FINDINGS,
    MAX_GOALS,
    MIN_DIMENSION_COVERAGE_FOR_FINDING,
    RULES_VERSION,
    SEVERITY_ORDER,
)

_EPSILON = 1e-9
_SEVERITY_RANK = {name: index for index, name in enumerate(SEVERITY_ORDER)}
_KIND_RANK = {name: index for index, name in enumerate(FINDING_KIND_ORDER)}


def _closed_evidence(evidence_ids: tuple[str, ...], metric_ids: set[str]) -> tuple[str, ...]:
    return tuple(evidence_id for evidence_id in evidence_ids if evidence_id in metric_ids)


class RuleEngine:
    def evaluate(
        self,
        *,
        role: AnalysisRole | None,
        metrics: tuple[MetricEvidence, ...],
        scores: ScoreBreakdown,
    ) -> tuple[tuple[Finding, ...], tuple[TrainingGoal, ...]]:
        metric_ids = {metric.evidence_id for metric in metrics}
        return (
            _select_findings(scores, metric_ids),
            _select_goals(role, metrics, metric_ids),
        )


def _select_findings(scores: ScoreBreakdown, metric_ids: set[str]) -> tuple[Finding, ...]:
    if scores.overall_score is None:
        return ()
    candidates: list[Finding] = []
    for dimension in scores.dimensions:
        if dimension.status != "available" or dimension.score is None:
            continue
        if dimension.coverage < MIN_DIMENSION_COVERAGE_FOR_FINDING:
            continue
        evidence_ids = _closed_evidence(dimension.evidence_ids, metric_ids)
        if not evidence_ids:
            continue
        if dimension.score >= FINDING_STRENGTH_MIN:
            candidates.append(
                _finding(
                    dimension.dimension,
                    "strength",
                    dimension.score,
                    dimension.coverage,
                    evidence_ids,
                )
            )
        if dimension.score <= FINDING_IMPROVEMENT_MAX:
            candidates.append(
                _finding(
                    dimension.dimension,
                    "improvement",
                    dimension.score,
                    dimension.coverage,
                    evidence_ids,
                )
            )
    candidates.sort(
        key=lambda item: (
            _SEVERITY_RANK[item.severity],
            _KIND_RANK[item.kind],
            DIMENSION_PRIORITIES[_dimension_from_rule(item.rule_id)],
            item.rule_id,
        )
    )
    return tuple(candidates[:MAX_FINDINGS])


def _finding(
    dimension: DimensionKey,
    kind: Literal["strength", "improvement"],
    score: float,
    coverage: float,
    evidence_ids: tuple[str, ...],
) -> Finding:
    if kind == "strength":
        severity: Literal["high", "medium"] = (
            "high" if score >= FINDING_STRENGTH_HIGH_MIN else "medium"
        )
    else:
        severity = "high" if score <= FINDING_IMPROVEMENT_HIGH_MAX else "medium"
    return Finding(
        rule_id=f"finding.{dimension}.{kind}",
        kind=kind,
        severity=severity,
        message_code=f"analysis.finding.{dimension}.{kind}",
        params={"score": score, "coverage": coverage},
        evidence_ids=evidence_ids,
        confidence=severity,
        requires_replay_interpretation=False,
    )


def _dimension_from_rule(rule_id: str) -> DimensionKey:
    return rule_id.split(".")[1]  # type: ignore[return-value]


def _select_goals(
    role: AnalysisRole | None,
    metrics: tuple[MetricEvidence, ...],
    metric_ids: set[str],
) -> tuple[TrainingGoal, ...]:
    if role is None:
        return ()
    targets = GOAL_TARGETS[role]
    candidates: list[tuple[float, str, TrainingGoal]] = []
    for metric in metrics:
        if metric.metric_key not in targets or metric.status != "available" or metric.value is None:
            continue
        target = targets[metric.metric_key]  # type: ignore[index]
        if target is None or metric.unit is None:
            continue
        evidence_ids = _closed_evidence((metric.evidence_id,), metric_ids)
        if not evidence_ids:
            continue
        current = metric.value
        if metric.beneficial_direction == "lower":
            if current <= target:
                continue
            gap = (current - target) / max(abs(target), _EPSILON)
        else:
            if current >= target:
                continue
            gap = (target - current) / max(abs(target), _EPSILON)
        rule_id = f"goal.{role}.{metric.metric_key}"
        candidates.append(
            (
                gap,
                rule_id,
                TrainingGoal(
                    rule_id=rule_id,
                    message_code=f"analysis.goal.{metric.metric_key}",
                    current_value=current,
                    target_value=target,
                    unit=metric.unit,
                    role=role,
                    evidence_ids=evidence_ids,
                    rules_version=RULES_VERSION,
                ),
            )
        )
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return tuple(item[2] for item in candidates[:MAX_GOALS])
