from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.core.routing import Platform
from app.schemas.domain import DomainModel, Locale, StaticDataStatus
from app.services.evidence.domain import EvidenceCategory, ReplayCoverageStatus
from app.services.replays.domain import ReplayArtifactKind

EvidenceRelationship = Literal[
    "killer",
    "victim",
    "assistant",
    "actor",
    "team_context",
    "not_involved",
]


class JointEvidenceRequest(DomainModel):
    platform: Platform
    puuid: str = Field(min_length=1, max_length=128)
    locale: Locale = Locale.EN_US
    replay_id: UUID | None = None


class PublicFactBase(DomainModel):
    fact_id: str
    timestamp_ms: int
    relationship: EvidenceRelationship


class PublicChampionKillFact(PublicFactBase):
    kind: Literal["champion_kill"]
    killer_id: int
    victim_id: int
    assisting_participant_ids: tuple[int, ...]
    position_x: int | None = None
    position_y: int | None = None


class PublicEliteMonsterKillFact(PublicFactBase):
    kind: Literal["elite_monster_kill"]
    killer_id: int
    killer_team_id: int
    monster_type: str
    monster_sub_type: str | None = None
    position_x: int | None = None
    position_y: int | None = None


class PublicBuildingKillFact(PublicFactBase):
    kind: Literal["building_kill"]
    killer_id: int
    team_id: int
    building_type: str
    lane_type: str | None = None
    tower_type: str | None = None
    position_x: int | None = None
    position_y: int | None = None


class PublicItemPurchasedFact(PublicFactBase):
    kind: Literal["item_purchased"]
    participant_id: int
    item_id: int
    item_name: str | None = None
    item_image_url: str | None = None


class PublicItemSoldFact(PublicFactBase):
    kind: Literal["item_sold"]
    participant_id: int
    item_id: int
    item_name: str | None = None
    item_image_url: str | None = None


class PublicItemDestroyedFact(PublicFactBase):
    kind: Literal["item_destroyed"]
    participant_id: int
    item_id: int
    item_name: str | None = None
    item_image_url: str | None = None


class PublicItemUndoFact(PublicFactBase):
    kind: Literal["item_undo"]
    participant_id: int
    before_id: int
    after_id: int
    before_item_name: str | None = None
    before_item_image_url: str | None = None
    after_item_name: str | None = None
    after_item_image_url: str | None = None


class PublicParticipantStateFact(PublicFactBase):
    kind: Literal["participant_state"]
    participant_id: int
    level: int
    current_gold: int
    total_gold: int
    minions_killed: int
    jungle_minions_killed: int
    xp: int
    position_x: int | None = None
    position_y: int | None = None


PublicTimelineFact = Annotated[
    PublicChampionKillFact
    | PublicEliteMonsterKillFact
    | PublicBuildingKillFact
    | PublicItemPurchasedFact
    | PublicItemSoldFact
    | PublicItemDestroyedFact
    | PublicItemUndoFact
    | PublicParticipantStateFact,
    Field(discriminator="kind"),
]


class EvidenceArtifactReferenceResponse(DomainModel):
    artifact_id: UUID
    kind: ReplayArtifactKind
    game_time_ms: int
    video_time_ms: int


class EvidenceWindowResponse(DomainModel):
    window_id: str
    start_ms: int
    end_ms: int
    categories: tuple[EvidenceCategory, ...]
    trigger_fact_ids: tuple[str, ...]
    coverage: ReplayCoverageStatus
    covered_game_start_ms: int | None = None
    covered_game_end_ms: int | None = None
    video_start_ms: int | None = None
    video_end_ms: int | None = None
    artifacts: tuple[EvidenceArtifactReferenceResponse, ...] = ()


class ReplayLinkSummary(DomainModel):
    status: Literal["linked"] = "linked"
    full_count: int
    partial_count: int
    unavailable_count: int


class JointEvidenceData(DomainModel):
    status: Literal["ready"] = "ready"
    platform: Platform
    match_id: str
    locale: Locale
    schema_version: Literal[1]
    facts: tuple[PublicTimelineFact, ...]
    windows: tuple[EvidenceWindowResponse, ...]
    timeline_cache_status: Literal["hit", "miss"]
    replay_link: ReplayLinkSummary | None
    static_data_status: StaticDataStatus
    truncated: bool
    total_window_count: int
    scope_notice_code: Literal["EVIDENCE_ONLY_NO_COACHING"] = "EVIDENCE_ONLY_NO_COACHING"


class JointEvidenceResponse(JointEvidenceData):
    request_id: str
