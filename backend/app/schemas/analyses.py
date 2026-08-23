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
        catalog = {metric.evidence_id for metric in self.metrics}
        referenced = (
            *(evidence_id for finding in self.findings for evidence_id in finding.evidence_ids),
            *(evidence_id for goal in self.goals for evidence_id in goal.evidence_ids),
        )
        if any(evidence_id not in catalog for evidence_id in referenced):
            raise ValueError("finding or goal references missing evidence")
        return self
