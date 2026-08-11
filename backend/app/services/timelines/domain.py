from __future__ import annotations

from typing import Literal

from app.core.routing import Platform
from app.schemas.domain import DomainModel

TIMELINE_SCHEMA_VERSION = 1

SupportedEventKind = Literal[
    "champion_kill",
    "elite_monster_kill",
    "building_kill",
    "item_purchased",
    "item_sold",
    "item_destroyed",
    "item_undo",
]

ItemEventKind = Literal[
    "item_purchased",
    "item_sold",
    "item_destroyed",
    "item_undo",
]


class TimelinePosition(DomainModel):
    x: int
    y: int


class ChampionKillFact(DomainModel):
    fact_id: str
    kind: Literal["champion_kill"]
    timestamp_ms: int
    frame_index: int
    event_index: int
    killer_id: int
    victim_id: int
    assisting_participant_ids: tuple[int, ...]
    position: TimelinePosition | None


class EliteMonsterKillFact(DomainModel):
    fact_id: str
    kind: Literal["elite_monster_kill"]
    timestamp_ms: int
    frame_index: int
    event_index: int
    killer_id: int
    killer_team_id: int
    monster_type: str
    monster_sub_type: str | None
    position: TimelinePosition | None


class BuildingKillFact(DomainModel):
    fact_id: str
    kind: Literal["building_kill"]
    timestamp_ms: int
    frame_index: int
    event_index: int
    killer_id: int
    team_id: int
    building_type: str
    lane_type: str | None
    tower_type: str | None
    position: TimelinePosition | None


class ItemEventFact(DomainModel):
    fact_id: str
    kind: ItemEventKind
    timestamp_ms: int
    frame_index: int
    event_index: int
    participant_id: int
    item_id: int | None = None
    before_id: int | None = None
    after_id: int | None = None


class ParticipantStateFact(DomainModel):
    fact_id: str
    kind: Literal["participant_state"]
    timestamp_ms: int
    frame_index: int
    participant_id: int
    level: int
    current_gold: int
    total_gold: int
    minions_killed: int
    jungle_minions_killed: int
    xp: int
    position: TimelinePosition | None


TimelineFact = (
    ChampionKillFact
    | EliteMonsterKillFact
    | BuildingKillFact
    | ItemEventFact
    | ParticipantStateFact
)


class TimelineSnapshot(DomainModel):
    platform: Platform
    match_id: str
    schema_version: Literal[1]
    frame_interval_ms: int
    participant_puuids: dict[int, str]
    facts: tuple[TimelineFact, ...]
