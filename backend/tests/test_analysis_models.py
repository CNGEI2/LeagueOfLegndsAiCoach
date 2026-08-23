from datetime import UTC, datetime
from uuid import uuid4

from app.core.routing import Platform
from app.models.analysis import AnalysisEvidenceRow, AnalysisJobRow
from app.services.analyses.domain import (
    DeterministicAnalysisResult,
    DimensionScore,
    MetricEvidence,
    ScoreBreakdown,
)


def test_analysis_job_row_maps_idempotency_and_version_columns() -> None:
    now = datetime.now(UTC)
    row = AnalysisJobRow(
        id=uuid4(),
        platform="NA1",
        match_id="NA1_1",
        selected_puuid="selected",
        idempotency_key="a" * 64,
        input_hash="b" * 64,
        status="completed",
        metric_version="deterministic-metrics-v1",
        score_version="deterministic-score-v1",
        rules_version="deterministic-rules-v1",
        created_at=now,
        updated_at=now,
        completed_at=now,
        expires_at=now,
    )
    assert row.__tablename__ == "analysis_jobs"
    assert row.idempotency_key == "a" * 64
    assert row.status == "completed"


def test_analysis_evidence_row_is_keyed_by_analysis_id() -> None:
    now = datetime.now(UTC)
    analysis_id = uuid4()
    row = AnalysisEvidenceRow(
        analysis_id=analysis_id,
        evidence_catalog=[{"evidence_id": "metric:v1:kda"}],
        deterministic_result={"schema_version": 1},
        input_hash="b" * 64,
        schema_version=1,
        created_at=now,
    )
    assert row.__tablename__ == "analysis_evidence"
    assert row.analysis_id == analysis_id
    assert row.schema_version == 1


def test_sample_result_is_locale_neutral() -> None:
    result = _sample_result()
    dumped = result.model_dump()
    assert "locale" not in dumped
    assert "replay_id" not in dumped


def _sample_result() -> DeterministicAnalysisResult:
    metric = MetricEvidence(
        evidence_id="metric:v1:kda",
        metric_key="kda",
        category="combat",
        status="available",
        value=6.0,
        unit="ratio",
        beneficial_direction="higher",
        comparisons=(),
        confidence="high",
        source_type="match",
        metric_version="deterministic-metrics-v1",
    )
    scores = ScoreBreakdown(
        role="support",
        dimensions=tuple(
            DimensionScore(
                dimension=dimension,
                status="available",
                score=50.0,
                configured_weight=20,
                applied_weight=20,
                coverage=1.0,
                evidence_ids=(metric.evidence_id,),
            )
            for dimension in (
                "economy",
                "combat",
                "survivability",
                "team_objectives",
                "vision",
            )
        ),
        overall_score=50.0,
        coverage=1.0,
        score_version="deterministic-score-v1",
    )
    return DeterministicAnalysisResult(
        status="completed",
        platform=Platform.NA1,
        match_id="NA1_123",
        selected_puuid="selected",
        role="support",
        metrics=(metric,),
        scores=scores,
        findings=(),
        goals=(),
        unavailable_reasons=(),
        input_hash="ab" * 32,
        metric_version="deterministic-metrics-v1",
        score_version="deterministic-score-v1",
        rules_version="deterministic-rules-v1",
        schema_version=1,
    )
