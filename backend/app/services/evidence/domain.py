from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.services.replays.domain import ReplayArtifactKind

EvidenceCategory = Literal[
    "combat_context",
    "death_context",
    "objective_context",
    "building_context",
]

EVIDENCE_CATEGORY_ORDER: tuple[EvidenceCategory, ...] = (
    "combat_context",
    "death_context",
    "objective_context",
    "building_context",
)

ReplayCoverageStatus = Literal["full", "partial", "unavailable"]


@dataclass(frozen=True)
class PlannedEvidenceWindow:
    window_id: str
    start_ms: int
    end_ms: int
    categories: tuple[EvidenceCategory, ...]
    trigger_fact_ids: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceWindowPlan:
    windows: tuple[PlannedEvidenceWindow, ...]
    truncated: bool
    total_window_count: int


@dataclass(frozen=True)
class EvidenceArtifactReference:
    artifact_id: UUID
    kind: ReplayArtifactKind
    game_time_ms: int
    video_time_ms: int


@dataclass(frozen=True)
class LinkedEvidenceWindow:
    window: PlannedEvidenceWindow
    coverage: ReplayCoverageStatus
    covered_game_start_ms: int | None
    covered_game_end_ms: int | None
    video_start_ms: int | None
    video_end_ms: int | None
    artifacts: tuple[EvidenceArtifactReference, ...]
