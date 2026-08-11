from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.core.routing import Platform
from app.services.riot.dto import (
    TimelineDto,
    TimelineEventDto,
    TimelineParticipantFrameDto,
    TimelinePositionDto,
)
from app.services.timelines.domain import (
    TIMELINE_SCHEMA_VERSION,
    BuildingKillFact,
    ChampionKillFact,
    EliteMonsterKillFact,
    ItemEventFact,
    ParticipantStateFact,
    SupportedEventKind,
    TimelineFact,
    TimelinePosition,
    TimelineSnapshot,
)

_SUPPORTED_EVENT_TYPE_TO_KIND: dict[str, SupportedEventKind] = {
    "CHAMPION_KILL": "champion_kill",
    "ELITE_MONSTER_KILL": "elite_monster_kill",
    "BUILDING_KILL": "building_kill",
    "ITEM_PURCHASED": "item_purchased",
    "ITEM_SOLD": "item_sold",
    "ITEM_DESTROYED": "item_destroyed",
    "ITEM_UNDO": "item_undo",
}


@dataclass(frozen=True)
class TimelineNormalizationResult:
    snapshot: TimelineSnapshot
    snapshot_hash: str
    supported_event_counts: dict[SupportedEventKind, int]
    ignored_event_count: int


class TimelineNormalizer:
    def normalize(
        self, *, platform: Platform, timeline: TimelineDto
    ) -> TimelineNormalizationResult:
        participant_puuids = {
            index: puuid for index, puuid in enumerate(timeline.metadata.participants, start=1)
        }
        facts: list[TimelineFact] = []
        supported_event_counts: dict[SupportedEventKind, int] = {
            kind: 0 for kind in _SUPPORTED_EVENT_TYPE_TO_KIND.values()
        }
        ignored_event_count = 0

        for frame_index, frame in enumerate(timeline.info.frames):
            for participant_id in sorted(frame.participant_frames):
                participant_frame = frame.participant_frames[participant_id]
                facts.append(
                    _participant_state_fact(
                        platform=platform,
                        match_id=timeline.metadata.match_id,
                        frame_index=frame_index,
                        timestamp_ms=frame.timestamp,
                        participant_frame=participant_frame,
                    )
                )

            for event_index, event in enumerate(frame.events):
                kind = _SUPPORTED_EVENT_TYPE_TO_KIND.get(event.type)
                if kind is None:
                    ignored_event_count += 1
                    continue
                facts.append(
                    _event_fact(
                        platform=platform,
                        match_id=timeline.metadata.match_id,
                        frame_index=frame_index,
                        event_index=event_index,
                        event=event,
                        kind=kind,
                    )
                )
                supported_event_counts[kind] += 1

        snapshot = TimelineSnapshot(
            platform=platform,
            match_id=timeline.metadata.match_id,
            schema_version=TIMELINE_SCHEMA_VERSION,
            frame_interval_ms=timeline.info.frame_interval,
            participant_puuids=participant_puuids,
            facts=tuple(facts),
        )
        return TimelineNormalizationResult(
            snapshot=snapshot,
            snapshot_hash=canonical_timeline_snapshot_hash(snapshot),
            supported_event_counts=supported_event_counts,
            ignored_event_count=ignored_event_count,
        )


def canonical_timeline_snapshot_hash(snapshot: TimelineSnapshot) -> str:
    payload = json.dumps(
        snapshot.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _fact_id(
    *,
    platform: Platform,
    match_id: str,
    frame_index: int,
    suffix: str,
) -> str:
    return (
        f"timeline:{platform.value}:{match_id}:v{TIMELINE_SCHEMA_VERSION}"
        f":frame:{frame_index}:{suffix}"
    )


def _map_position(position: TimelinePositionDto | None) -> TimelinePosition | None:
    if position is None:
        return None
    return TimelinePosition(x=position.x, y=position.y)


def _participant_state_fact(
    *,
    platform: Platform,
    match_id: str,
    frame_index: int,
    timestamp_ms: int,
    participant_frame: TimelineParticipantFrameDto,
) -> ParticipantStateFact:
    participant_id = participant_frame.participant_id
    return ParticipantStateFact(
        fact_id=_fact_id(
            platform=platform,
            match_id=match_id,
            frame_index=frame_index,
            suffix=f"participant:{participant_id}",
        ),
        kind="participant_state",
        timestamp_ms=timestamp_ms,
        frame_index=frame_index,
        participant_id=participant_id,
        level=participant_frame.level,
        current_gold=participant_frame.current_gold,
        total_gold=participant_frame.total_gold,
        minions_killed=participant_frame.minions_killed,
        jungle_minions_killed=participant_frame.jungle_minions_killed,
        xp=participant_frame.xp,
        position=_map_position(participant_frame.position),
    )


def _event_fact(
    *,
    platform: Platform,
    match_id: str,
    frame_index: int,
    event_index: int,
    event: TimelineEventDto,
    kind: SupportedEventKind,
) -> TimelineFact:
    fact_id = _fact_id(
        platform=platform,
        match_id=match_id,
        frame_index=frame_index,
        suffix=f"event:{event_index}",
    )
    position = _map_position(event.position)
    if kind == "champion_kill":
        assistants = event.assisting_participant_ids or ()
        return ChampionKillFact(
            fact_id=fact_id,
            kind="champion_kill",
            timestamp_ms=event.timestamp,
            frame_index=frame_index,
            event_index=event_index,
            killer_id=event.killer_id if event.killer_id is not None else 0,
            victim_id=event.victim_id if event.victim_id is not None else 0,
            assisting_participant_ids=tuple(dict.fromkeys(assistants)),
            position=position,
        )
    if kind == "elite_monster_kill":
        return EliteMonsterKillFact(
            fact_id=fact_id,
            kind="elite_monster_kill",
            timestamp_ms=event.timestamp,
            frame_index=frame_index,
            event_index=event_index,
            killer_id=event.killer_id if event.killer_id is not None else 0,
            killer_team_id=event.killer_team_id if event.killer_team_id is not None else 0,
            monster_type=event.monster_type or "",
            monster_sub_type=event.monster_sub_type,
            position=position,
        )
    if kind == "building_kill":
        return BuildingKillFact(
            fact_id=fact_id,
            kind="building_kill",
            timestamp_ms=event.timestamp,
            frame_index=frame_index,
            event_index=event_index,
            killer_id=event.killer_id if event.killer_id is not None else 0,
            team_id=event.team_id if event.team_id is not None else 0,
            building_type=event.building_type or "",
            lane_type=event.lane_type,
            tower_type=event.tower_type,
            position=position,
        )
    if kind == "item_undo":
        return ItemEventFact(
            fact_id=fact_id,
            kind="item_undo",
            timestamp_ms=event.timestamp,
            frame_index=frame_index,
            event_index=event_index,
            participant_id=event.participant_id if event.participant_id is not None else 0,
            item_id=None,
            before_id=event.before_id,
            after_id=event.after_id,
        )
    return ItemEventFact(
        fact_id=fact_id,
        kind=kind,
        timestamp_ms=event.timestamp,
        frame_index=frame_index,
        event_index=event_index,
        participant_id=event.participant_id if event.participant_id is not None else 0,
        item_id=event.item_id,
        before_id=None,
        after_id=None,
    )
