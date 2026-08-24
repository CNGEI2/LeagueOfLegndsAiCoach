from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal, Self

from pydantic import Field, model_validator

from app.core.routing import Platform
from app.schemas.domain import DomainModel

AnalysisRole = Literal["top", "jungle", "mid", "bottom", "support"]
DimensionKey = Literal["economy", "combat", "survivability", "team_objectives", "vision"]
MetricStatus = Literal["available", "unavailable"]
UnavailableReason = Literal[
    "missing_match_value",
    "invalid_duration",
    "division_by_zero",
    "timeline_unavailable",
    "role_unavailable",
    "opponent_unavailable",
    "opponent_ambiguous",
    "insufficient_team_values",
]

DIMENSION_ORDER: tuple[DimensionKey, ...] = (
    "economy",
    "combat",
    "survivability",
    "team_objectives",
    "vision",
)
OVERALL_COVERAGE_THRESHOLD = 0.60

_UPSTREAM_ROLE_MAP: Mapping[str, AnalysisRole] = MappingProxyType(
    {
        "TOP": "top",
        "JUNGLE": "jungle",
        "MIDDLE": "mid",
        "BOTTOM": "bottom",
        "UTILITY": "support",
    }
)


def normalize_analysis_role(upstream: str | None) -> AnalysisRole | None:
    if upstream is None:
        return None
    return _UPSTREAM_ROLE_MAP.get(upstream)


class MetricComparison(DomainModel):
    basis: Literal["team_percentile", "same_role"]
    score: float = Field(ge=0, le=100)
    opponent_value: float | None = None


class MetricEvidence(DomainModel):
    evidence_id: str
    metric_key: str
    category: DimensionKey
    status: MetricStatus
    value: float | None
    unit: str | None
    beneficial_direction: Literal["higher", "lower"]
    comparisons: tuple[MetricComparison, ...]
    confidence: Literal["high", "medium", "low"]
    source_type: Literal["match", "timeline", "match_and_timeline"]
    source_fact_ids: tuple[str, ...] = ()
    unavailable_reason: UnavailableReason | None = None
    metric_version: str

    @model_validator(mode="after")
    def validate_availability_shape(self) -> Self:
        bases = tuple(comparison.basis for comparison in self.comparisons)
        if len(bases) != len(set(bases)):
            raise ValueError("comparisons must be unique by basis")
        if self.status == "available":
            if self.value is None or self.unit is None:
                raise ValueError("available metrics require a value and unit")
            if self.unavailable_reason is not None:
                raise ValueError("available metrics must not set unavailable_reason")
            return self
        if self.value is not None:
            raise ValueError("unavailable metrics must not set a value")
        if self.unavailable_reason is None:
            raise ValueError("unavailable metrics require unavailable_reason")
        return self


class DimensionScore(DomainModel):
    dimension: DimensionKey
    status: Literal["available", "unavailable"]
    score: float | None = Field(default=None, ge=0, le=100)
    configured_weight: float = Field(ge=0, le=100)
    applied_weight: float = Field(ge=0, le=100)
    coverage: float = Field(ge=0, le=1)
    evidence_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_availability_shape(self) -> Self:
        if self.status == "available":
            if self.score is None:
                raise ValueError("available dimension scores require a score")
            return self
        if self.score is not None:
            raise ValueError("unavailable dimension scores must not set a score")
        return self


class ScoreBreakdown(DomainModel):
    role: AnalysisRole | None
    dimensions: tuple[DimensionScore, ...]
    overall_score: float | None = Field(default=None, ge=0, le=100)
    coverage: float = Field(ge=0, le=1)
    score_version: str

    @model_validator(mode="after")
    def validate_dimension_order(self) -> Self:
        observed = tuple(item.dimension for item in self.dimensions)
        if observed != DIMENSION_ORDER:
            raise ValueError("scores require five unique dimensions in canonical order")
        overall_forbidden = self.role is None or self.coverage < OVERALL_COVERAGE_THRESHOLD
        if overall_forbidden and self.overall_score is not None:
            raise ValueError("overall score requires a known role and sufficient coverage")
        return self


class Finding(DomainModel):
    rule_id: str
    kind: Literal["strength", "improvement"]
    severity: Literal["high", "medium", "low"]
    message_code: str
    params: dict[str, str | int | float]
    evidence_ids: tuple[str, ...]
    confidence: Literal["high", "medium", "low"]
    requires_replay_interpretation: bool = False


class TrainingGoal(DomainModel):
    rule_id: str
    message_code: str
    current_value: float
    target_value: float
    unit: str
    role: AnalysisRole
    evidence_ids: tuple[str, ...]
    rules_version: str


class DeterministicAnalysisResult(DomainModel):
    status: Literal["completed", "partial"]
    platform: Platform
    match_id: str
    selected_puuid: str
    role: AnalysisRole | None
    metrics: tuple[MetricEvidence, ...]
    scores: ScoreBreakdown
    findings: tuple[Finding, ...]
    goals: tuple[TrainingGoal, ...]
    unavailable_reasons: tuple[UnavailableReason, ...]
    input_hash: str
    metric_version: str
    score_version: str
    rules_version: str
    schema_version: Literal[1]

    @model_validator(mode="after")
    def validate_cross_field_integrity(self) -> Self:
        evidence_ids = tuple(metric.evidence_id for metric in self.metrics)
        metric_keys = tuple(metric.metric_key for metric in self.metrics)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("metric evidence ids must be unique")
        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError("metric keys must be unique")
        catalog = set(evidence_ids)
        referenced = (
            *(
                evidence_id
                for dimension in self.scores.dimensions
                for evidence_id in dimension.evidence_ids
            ),
            *(evidence_id for finding in self.findings for evidence_id in finding.evidence_ids),
            *(evidence_id for goal in self.goals for evidence_id in goal.evidence_ids),
        )
        if any(evidence_id not in catalog for evidence_id in referenced):
            raise ValueError("analysis result references missing evidence")
        if self.scores.role != self.role:
            raise ValueError("score role must match result role")
        if any(goal.role != self.role for goal in self.goals):
            raise ValueError("goal roles must match result role")
        if any(metric.metric_version != self.metric_version for metric in self.metrics):
            raise ValueError("metric versions must match result version")
        if self.scores.score_version != self.score_version:
            raise ValueError("score versions must match result version")
        if any(goal.rules_version != self.rules_version for goal in self.goals):
            raise ValueError("goal rules versions must match result version")
        score_unavailable = self.role is None or self.scores.coverage < OVERALL_COVERAGE_THRESHOLD
        if score_unavailable and self.status != "partial":
            raise ValueError("unavailable overall score requires partial status")
        if score_unavailable and self.findings:
            raise ValueError("unavailable overall score must not include findings")
        return self
