from __future__ import annotations

from app.core.metrics import MetricsRegistry
from app.services.evidence.service import JointEvidenceService


def test_registry_exposes_closed_joint_evidence_composition_metrics() -> None:
    registry = MetricsRegistry()
    registry.joint_evidence_windows_total.inc(result="planned")
    registry.joint_evidence_window_truncations_total.inc(result="truncated")
    registry.joint_evidence_window_truncations_total.inc(result="not_truncated")
    registry.joint_evidence_replay_coverage_total.inc(coverage="full")
    registry.joint_evidence_replay_coverage_total.inc(coverage="partial")
    registry.joint_evidence_replay_coverage_total.inc(coverage="unavailable")
    registry.joint_evidence_api_requests_total.inc(outcome="ready", error_code="none")
    registry.joint_evidence_api_requests_total.inc(
        outcome="error", error_code="MATCH_TIMELINE_NOT_FOUND"
    )

    rendered = registry.render_prometheus_text()
    assert 'joint_evidence_windows_total{result="planned"} 1.0' in rendered
    assert 'joint_evidence_window_truncations_total{result="truncated"} 1.0' in rendered
    assert 'joint_evidence_window_truncations_total{result="not_truncated"} 1.0' in rendered
    assert 'joint_evidence_replay_coverage_total{coverage="full"} 1.0' in rendered
    assert 'joint_evidence_replay_coverage_total{coverage="partial"} 1.0' in rendered
    assert 'joint_evidence_replay_coverage_total{coverage="unavailable"} 1.0' in rendered
    assert 'joint_evidence_api_requests_total{error_code="none",outcome="ready"} 1.0' in rendered
    assert (
        'joint_evidence_api_requests_total{error_code="MATCH_TIMELINE_NOT_FOUND",outcome="error"}'
        " 1.0" in rendered
    )
    for banned in ("puuid", "match_id", "token", "NA1_", "artifact"):
        assert banned not in rendered


def test_joint_evidence_metric_label_allowlists_are_closed() -> None:
    assert frozenset({"planned"}) == JointEvidenceService.WINDOW_RESULTS
    assert frozenset({"truncated", "not_truncated"}) == JointEvidenceService.TRUNCATION_RESULTS
    assert frozenset({"full", "partial", "unavailable"}) == JointEvidenceService.COVERAGE_LABELS
    assert frozenset({"ready", "error"}) == JointEvidenceService.API_OUTCOMES
    assert "none" in JointEvidenceService.API_ERROR_CODES
    assert "MATCH_EVIDENCE_UNSUPPORTED_MODE" in JointEvidenceService.API_ERROR_CODES
    assert "VALIDATION_ERROR" in JointEvidenceService.API_ERROR_CODES
    assert "REPLAY_EVIDENCE_NOT_READY" in JointEvidenceService.API_ERROR_CODES
