from typing import Any

from app.services.evidence.domain import (
    EvidenceArtifactReference,
    EvidenceCategory,
    EvidenceWindowPlan,
    LinkedEvidenceWindow,
    PlannedEvidenceWindow,
    ReplayCoverageStatus,
)

__all__ = [
    "EvidenceArtifactReference",
    "EvidenceCategory",
    "EvidenceWindowPlan",
    "EvidenceWindowPlanner",
    "LinkedEvidenceWindow",
    "PlannedEvidenceWindow",
    "ReplayCoverageStatus",
    "ReplayEvidenceLinker",
]


def __getattr__(name: str) -> Any:
    if name == "EvidenceWindowPlanner":
        from app.services.evidence.windows import EvidenceWindowPlanner

        return EvidenceWindowPlanner
    if name == "ReplayEvidenceLinker":
        from app.services.evidence.replay import ReplayEvidenceLinker

        return ReplayEvidenceLinker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
