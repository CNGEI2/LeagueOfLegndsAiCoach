from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, model_validator

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


def _parse_strict_domain_int(value: object) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise ValueError("expected a strict integer")
    return value


StrictDomainInt = Annotated[int, BeforeValidator(_parse_strict_domain_int)]


def _parse_participant_id_key(key: object) -> int:
    if isinstance(key, bool) or key is None:
        raise ValueError("participant id key must be a decimal participant id")
    if type(key) is int:
        if key < 1:
            raise ValueError("participant id key must be positive")
        return key
    if isinstance(key, str):
        if not key.isdigit():
            raise ValueError("participant id key must be a decimal participant id")
        parsed = int(key)
        if parsed < 1 or str(parsed) != key:
            raise ValueError("participant id key must be a decimal participant id")
        return parsed
    raise ValueError("participant id key must be a decimal participant id")


def _parse_participant_puuids(value: object) -> dict[int, str]:
    if not isinstance(value, dict):
        raise ValueError("participant_puuids must be an object")
    converted: dict[int, str] = {}
    for key, puuid in value.items():
        participant_id = _parse_participant_id_key(key)
        if participant_id in converted:
            raise ValueError("duplicate participant id")
        if not isinstance(puuid, str):
            raise ValueError("participant puuid must be a string")
        converted[participant_id] = puuid
    return converted


ParticipantPuuids = Annotated[dict[int, str], BeforeValidator(_parse_participant_puuids)]


class TimelinePosition(DomainModel):
    x: StrictDomainInt
    y: StrictDomainInt


class ChampionKillFact(DomainModel):
    fact_id: str
    kind: Literal["champion_kill"]
    timestamp_ms: StrictDomainInt
    frame_index: StrictDomainInt
    event_index: StrictDomainInt
    killer_id: StrictDomainInt
    victim_id: StrictDomainInt
    assisting_participant_ids: tuple[StrictDomainInt, ...]
    position: TimelinePosition | None


class EliteMonsterKillFact(DomainModel):
    fact_id: str
    kind: Literal["elite_monster_kill"]
    timestamp_ms: StrictDomainInt
    frame_index: StrictDomainInt
    event_index: StrictDomainInt
    killer_id: StrictDomainInt
    killer_team_id: StrictDomainInt
    monster_type: str
    monster_sub_type: str | None
    position: TimelinePosition | None


class BuildingKillFact(DomainModel):
    fact_id: str
    kind: Literal["building_kill"]
    timestamp_ms: StrictDomainInt
    frame_index: StrictDomainInt
    event_index: StrictDomainInt
    killer_id: StrictDomainInt
    team_id: StrictDomainInt
    building_type: str
    lane_type: str | None
    tower_type: str | None
    position: TimelinePosition | None


class ItemEventFact(DomainModel):
    fact_id: str
    kind: ItemEventKind
    timestamp_ms: StrictDomainInt
    frame_index: StrictDomainInt
    event_index: StrictDomainInt
    participant_id: StrictDomainInt
    item_id: StrictDomainInt | None = None
    before_id: StrictDomainInt | None = None
    after_id: StrictDomainInt | None = None

    @model_validator(mode="after")
    def validate_item_shape(self) -> Self:
        if self.kind == "item_undo":
            if self.item_id is not None:
                raise ValueError("item undo must not set item_id")
            if self.before_id is None or self.after_id is None:
                raise ValueError("item undo requires before_id and after_id")
            return self
        if self.item_id is None:
            raise ValueError("item event requires item_id")
        if self.before_id is not None or self.after_id is not None:
            raise ValueError("item event must not set before_id or after_id")
        return self


class ParticipantStateFact(DomainModel):
    fact_id: str
    kind: Literal["participant_state"]
    timestamp_ms: StrictDomainInt
    frame_index: StrictDomainInt
    participant_id: StrictDomainInt
    level: StrictDomainInt
    current_gold: StrictDomainInt
    total_gold: StrictDomainInt
    minions_killed: StrictDomainInt
    jungle_minions_killed: StrictDomainInt
    xp: StrictDomainInt
    position: TimelinePosition | None


TimelineFact = Annotated[
    ChampionKillFact
    | EliteMonsterKillFact
    | BuildingKillFact
    | ItemEventFact
    | ParticipantStateFact,
    Field(discriminator="kind"),
]


class TimelineSnapshot(DomainModel):
    platform: Platform
    match_id: str
    schema_version: Annotated[Literal[1], BeforeValidator(_parse_strict_domain_int)]
    frame_interval_ms: StrictDomainInt
    participant_puuids: ParticipantPuuids
    facts: tuple[TimelineFact, ...]
