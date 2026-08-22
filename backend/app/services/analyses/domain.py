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
