from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.core.routing import Platform
from app.schemas.domain import DomainModel, Locale
from app.services.analyses.domain import (
    AnalysisRole,
    Finding,
    MetricEvidence,
    ScoreBreakdown,
    TrainingGoal,
    UnavailableReason,
)

_SHA256 = r"^[a-f0-9]{64}$"


class AnalysisCreateRequest(DomainModel):
    platform: Platform
    match_id: str = Field(min_length=1, max_length=64)
    puuid: str = Field(min_length=1, max_length=128)
    locale: Locale = Locale.EN_US


class AnalysisResponse(DomainModel):
    analysis_id: UUID
    status: Literal["completed", "partial"]
    cached: bool
    locale: Locale
    role: AnalysisRole | None
    metrics: tuple[MetricEvidence, ...]
    scores: ScoreBreakdown
    findings: tuple[Finding, ...] = Field(max_length=3)
    goals: tuple[TrainingGoal, ...] = Field(max_length=3)
    unavailable_reasons: tuple[UnavailableReason, ...]
    input_hash: str = Field(pattern=_SHA256)
    metric_version: str
    score_version: str
    rules_version: str
    schema_version: Literal[1]
    scope_notice_code: Literal["DETERMINISTIC_DATA_COACHING_NO_AI"]
    request_id: str

    @model_validator(mode="after")
    def validate_evidence_references(self) -> Self:
        evidence_ids = tuple(metric.evidence_id for metric in self.metrics)
        metric_keys = tuple(metric.metric_key for metric in self.metrics)
        if len(evidence_ids) != len(set(evidence_ids)) or len(metric_keys) != len(set(metric_keys)):
            raise ValueError("analysis metrics must be unique")
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
            raise ValueError("analysis response references missing evidence")
        if self.scores.role != self.role or any(goal.role != self.role for goal in self.goals):
            raise ValueError("analysis response roles must agree")
        if any(metric.metric_version != self.metric_version for metric in self.metrics):
            raise ValueError("analysis response metric versions must agree")
        if self.scores.score_version != self.score_version:
            raise ValueError("analysis response score versions must agree")
        if any(goal.rules_version != self.rules_version for goal in self.goals):
            raise ValueError("analysis response rules versions must agree")
        return self
