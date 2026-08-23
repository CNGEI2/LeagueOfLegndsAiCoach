from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.routing import Platform
from app.repositories.analyses import StoredAnalysis
from app.services.analyses.domain import (
    DeterministicAnalysisResult,
    DimensionScore,
    MetricEvidence,
    ScoreBreakdown,
)

VALID_KEY = "ab" * 32


def make_analysis_result(**overrides: object) -> DeterministicAnalysisResult:
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
    values: dict[str, object] = {
        "status": "completed",
        "platform": Platform.NA1,
        "match_id": "NA1_123",
        "selected_puuid": "selected",
        "role": "support",
        "metrics": (metric,),
        "scores": scores,
        "findings": (),
        "goals": (),
        "unavailable_reasons": (),
        "input_hash": VALID_KEY,
        "metric_version": "deterministic-metrics-v1",
        "score_version": "deterministic-score-v1",
        "rules_version": "deterministic-rules-v1",
        "schema_version": 1,
    }
    values.update(overrides)
    return DeterministicAnalysisResult(**values)  # type: ignore[arg-type]


def _stored(**overrides: object) -> StoredAnalysis:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "analysis_id": uuid4(),
        "idempotency_key": VALID_KEY,
        "result": make_analysis_result(),
        "created_at": now,
        "expires_at": now + timedelta(days=30),
    }
    values.update(overrides)
    return StoredAnalysis(**values)  # type: ignore[arg-type]


def test_stored_analysis_requires_timezone_aware_timestamps() -> None:
    naive = datetime(2026, 8, 22, 12, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        _stored(created_at=naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        _stored(expires_at=naive)


def test_stored_analysis_requires_lowercase_sha256_keys() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _stored(idempotency_key="AB" * 32)
    with pytest.raises(ValueError, match="SHA-256"):
        _stored(idempotency_key="abc")
    stored = _stored()
    assert len(stored.idempotency_key) == 64
    assert stored.idempotency_key == stored.idempotency_key.lower()
    assert stored.result.input_hash == VALID_KEY


def test_stored_analysis_result_hash_is_lowercase_sha256() -> None:
    stored = _stored()
    assert stored.result.input_hash == VALID_KEY
    with pytest.raises(ValueError, match="input_hash"):
        _stored(result=make_analysis_result(input_hash="CD" * 32))
