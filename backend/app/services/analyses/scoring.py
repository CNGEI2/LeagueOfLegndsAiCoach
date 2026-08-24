from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from app.services.analyses.domain import (
    DIMENSION_ORDER,
    AnalysisRole,
    DimensionKey,
    DimensionScore,
    MetricEvidence,
    ScoreBreakdown,
)
from app.services.analyses.rules_v1 import (
    DIMENSION_SIGNALS,
    OVERALL_COVERAGE_THRESHOLD,
    ROLE_WEIGHTS,
    SCORE_VERSION,
)

ComparisonBasis = Literal["team_percentile", "same_role"]


def meets_overall_threshold(coverage: float) -> bool:
    return coverage >= OVERALL_COVERAGE_THRESHOLD


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _round_score(value: float) -> float:
    return round(_clamp(value, 0.0, 100.0), 2)


def _round_coverage(value: float) -> float:
    return round(_clamp(value, 0.0, 1.0), 4)


def _signal_source(signal_key: str) -> tuple[str, ComparisonBasis]:
    if signal_key.endswith("_same_role"):
        return signal_key[: -len("_same_role")], "same_role"
    if signal_key.endswith("_team"):
        return signal_key[: -len("_team")], "team_percentile"
    raise ValueError(f"unknown scoring signal: {signal_key}")


def _signal_score(
    signal_key: str, metric_by_key: Mapping[str, MetricEvidence]
) -> tuple[float, str] | None:
    metric_key, basis = _signal_source(signal_key)
    metric = metric_by_key.get(metric_key)
    if metric is None or metric.status != "available":
        return None
    for comparison in metric.comparisons:
        if comparison.basis == basis:
            return comparison.score, metric.evidence_id
    return None


def _dimension_score(
    dimension: DimensionKey,
    metric_by_key: Mapping[str, MetricEvidence],
    *,
    configured_weight: float,
) -> tuple[DimensionScore, float]:
    declared_signals = DIMENSION_SIGNALS[dimension]
    declared_weight = float(sum(declared_signals.values()))
    available_weight = 0.0
    weighted_score = 0.0
    evidence_ids: list[str] = []
    for signal_key, signal_weight in declared_signals.items():
        extracted = _signal_score(signal_key, metric_by_key)
        if extracted is None:
            continue
        score, evidence_id = extracted
        available_weight += signal_weight
        weighted_score += score * signal_weight
        if evidence_id not in evidence_ids:
            evidence_ids.append(evidence_id)
    coverage = 0.0 if declared_weight == 0 else available_weight / declared_weight
    raw_applied = configured_weight * coverage
    if available_weight == 0:
        return (
            DimensionScore(
                dimension=dimension,
                status="unavailable",
                score=None,
                configured_weight=_round_score(configured_weight),
                applied_weight=0.0,
                coverage=_round_coverage(coverage),
                evidence_ids=(),
            ),
            raw_applied,
        )
    return (
        DimensionScore(
            dimension=dimension,
            status="available",
            score=_round_score(weighted_score / available_weight),
            configured_weight=_round_score(configured_weight),
            applied_weight=0.0,
            coverage=_round_coverage(coverage),
            evidence_ids=tuple(evidence_ids),
        ),
        raw_applied,
    )


class ScoreEngine:
    def compute(
        self,
        *,
        role: AnalysisRole | None,
        metrics: tuple[MetricEvidence, ...],
    ) -> ScoreBreakdown:
        metric_by_key = {metric.metric_key: metric for metric in metrics}
        role_weights = ROLE_WEIGHTS.get(role, {}) if role is not None else {}
        built: list[tuple[DimensionScore, float]] = []
        for dimension in DIMENSION_ORDER:
            built.append(
                _dimension_score(
                    dimension,
                    metric_by_key,
                    configured_weight=float(role_weights.get(dimension, 0)),
                )
            )
        raw_total = sum(raw for _item, raw in built)
        overall_coverage = raw_total / 100.0
        qualifies = role is not None and meets_overall_threshold(overall_coverage)
        dimensions: list[DimensionScore] = []
        overall_numerator = 0.0
        for item, raw in built:
            applied = _round_score((raw / raw_total) * 100.0) if qualifies and raw_total else 0.0
            dimensions.append(item.model_copy(update={"applied_weight": applied}))
            if qualifies and item.score is not None:
                overall_numerator += item.score * raw
        overall_score = (
            _round_score(overall_numerator / raw_total) if qualifies and raw_total else None
        )
        return ScoreBreakdown(
            role=role,
            dimensions=tuple(dimensions),
            overall_score=overall_score,
            coverage=_round_coverage(overall_coverage) if role is not None else 0.0,
            score_version=SCORE_VERSION,
        )
