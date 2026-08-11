from __future__ import annotations

import copy
import hashlib
import json
from types import UnionType
from typing import Annotated, Union, get_args, get_origin

import pytest
from pydantic import TypeAdapter, ValidationError
from pydantic.fields import FieldInfo

from app.core.routing import Platform
from app.services.riot.dto import validate_timeline_payload
from app.services.timelines.domain import (
    TIMELINE_SCHEMA_VERSION,
    BuildingKillFact,
    ChampionKillFact,
    EliteMonsterKillFact,
    ItemEventFact,
    ParticipantStateFact,
    TimelineFact,
    TimelinePosition,
    TimelineSnapshot,
)
from app.services.timelines.normalizer import TimelineNormalizer, canonical_timeline_snapshot_hash
from tests.fixtures.riot_payloads import (
    timeline_payload_for_normalizer,
    timeline_payload_with_optional_gaps,
)


def _normalize(
    payload: dict[str, object] | None = None,
    *,
    platform: Platform = Platform.NA1,
    match_id: str = "NA1_fixture",
):
    raw = timeline_payload_for_normalizer(match_id=match_id) if payload is None else payload
    timeline = validate_timeline_payload(raw, match_id=match_id)
    return TimelineNormalizer().normalize(platform=platform, timeline=timeline)


def test_timeline_schema_version_is_one() -> None:
    assert TIMELINE_SCHEMA_VERSION == 1


def test_timeline_snapshot_and_facts_are_frozen_forbid_extra() -> None:
    result = _normalize()
    snapshot = result.snapshot
    assert snapshot.model_config["frozen"] is True
    assert snapshot.model_config["extra"] == "forbid"
    with pytest.raises(ValidationError):
        TimelineSnapshot.model_validate({**snapshot.model_dump(mode="json"), "raw_dto": {}})
    for fact in snapshot.facts:
        assert fact.model_config["frozen"] is True
        assert fact.model_config["extra"] == "forbid"
        with pytest.raises(ValidationError):
            type(fact).model_validate({**fact.model_dump(mode="json"), "unexpected": True})


def _timeline_fact_union_members() -> tuple[type, ...]:
    assert get_origin(TimelineFact) is Annotated
    union_type, field_info = get_args(TimelineFact)
    assert isinstance(field_info, FieldInfo)
    assert field_info.discriminator == "kind"
    assert get_origin(union_type) in {Union, UnionType}
    return get_args(union_type)


def test_timeline_fact_is_kind_discriminated_union() -> None:
    members = _timeline_fact_union_members()
    assert ChampionKillFact in members
    assert EliteMonsterKillFact in members
    assert BuildingKillFact in members
    assert ItemEventFact in members
    assert ParticipantStateFact in members


def test_timeline_fact_adapter_parses_by_kind_discriminator() -> None:
    adapter = TypeAdapter(TimelineFact)
    kill = adapter.validate_python(
        {
            "fact_id": "timeline:NA1:NA1_fixture:v1:frame:1:event:0",
            "kind": "champion_kill",
            "timestamp_ms": 61_000,
            "frame_index": 1,
            "event_index": 0,
            "killer_id": 1,
            "victim_id": 6,
            "assisting_participant_ids": [2, 3],
            "position": {"x": 4000, "y": 5000},
        }
    )
    assert isinstance(kill, ChampionKillFact)
    purchased = adapter.validate_python(
        {
            "fact_id": "timeline:NA1:NA1_fixture:v1:frame:0:event:0",
            "kind": "item_purchased",
            "timestamp_ms": 1_000,
            "frame_index": 0,
            "event_index": 0,
            "participant_id": 1,
            "item_id": 1055,
            "before_id": None,
            "after_id": None,
        }
    )
    assert isinstance(purchased, ItemEventFact)
    assert purchased.kind == "item_purchased"
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "fact_id": "timeline:NA1:NA1_fixture:v1:frame:1:event:0",
                "kind": "champion_kill",
                "timestamp_ms": 61_000,
                "frame_index": 1,
                "event_index": 0,
                "killer_id": 1,
                "victim_id": 6,
                "assisting_participant_ids": [2, 3],
                "position": {"x": 4000, "y": 5000},
                "item_id": 1055,
            }
        )


def test_item_event_fact_shape_is_strict_and_preserves_zero() -> None:
    purchased = ItemEventFact(
        fact_id="timeline:NA1:m:v1:frame:0:event:0",
        kind="item_purchased",
        timestamp_ms=1_000,
        frame_index=0,
        event_index=0,
        participant_id=1,
        item_id=0,
        before_id=None,
        after_id=None,
    )
    assert purchased.item_id == 0
    with pytest.raises(ValidationError):
        ItemEventFact(
            fact_id="timeline:NA1:m:v1:frame:0:event:0",
            kind="item_purchased",
            timestamp_ms=1_000,
            frame_index=0,
            event_index=0,
            participant_id=1,
            item_id=1055,
            before_id=0,
            after_id=None,
        )
    with pytest.raises(ValidationError):
        ItemEventFact(
            fact_id="timeline:NA1:m:v1:frame:0:event:0",
            kind="item_purchased",
            timestamp_ms=1_000,
            frame_index=0,
            event_index=0,
            participant_id=1,
            item_id=None,
            before_id=None,
            after_id=None,
        )
    undo = ItemEventFact(
        fact_id="timeline:NA1:m:v1:frame:0:event:1",
        kind="item_undo",
        timestamp_ms=2_000,
        frame_index=0,
        event_index=1,
        participant_id=1,
        item_id=None,
        before_id=0,
        after_id=0,
    )
    assert undo.before_id == 0
    assert undo.after_id == 0
    with pytest.raises(ValidationError):
        ItemEventFact(
            fact_id="timeline:NA1:m:v1:frame:0:event:1",
            kind="item_undo",
            timestamp_ms=2_000,
            frame_index=0,
            event_index=1,
            participant_id=1,
            item_id=1055,
            before_id=0,
            after_id=0,
        )
    with pytest.raises(ValidationError):
        ItemEventFact(
            fact_id="timeline:NA1:m:v1:frame:0:event:1",
            kind="item_undo",
            timestamp_ms=2_000,
            frame_index=0,
            event_index=1,
            participant_id=1,
            item_id=None,
            before_id=None,
            after_id=0,
        )


def test_timeline_snapshot_rejects_numeric_coercion_except_participant_keys() -> None:
    dumped = _normalize().snapshot.model_dump(mode="json")
    restored = TimelineSnapshot.model_validate(dumped)
    assert restored.participant_puuids == {
        index: f"fixture-puuid-{index}" for index in range(1, 11)
    }
    assert all(type(key) is int for key in restored.participant_puuids)

    stringified_interval = copy.deepcopy(dumped)
    stringified_interval["frame_interval_ms"] = str(stringified_interval["frame_interval_ms"])
    with pytest.raises(ValidationError):
        TimelineSnapshot.model_validate(stringified_interval)

    float_interval = copy.deepcopy(dumped)
    float_interval["frame_interval_ms"] = float(float_interval["frame_interval_ms"])
    with pytest.raises(ValidationError):
        TimelineSnapshot.model_validate(float_interval)

    bool_interval = copy.deepcopy(dumped)
    bool_interval["frame_interval_ms"] = True
    with pytest.raises(ValidationError):
        TimelineSnapshot.model_validate(bool_interval)

    nested = copy.deepcopy(dumped)
    kill = next(fact for fact in nested["facts"] if fact["kind"] == "champion_kill")
    kill["killer_id"] = str(kill["killer_id"])
    with pytest.raises(ValidationError):
        TimelineSnapshot.model_validate(nested)

    padded_key = copy.deepcopy(dumped)
    padded_key["participant_puuids"] = {"01": "fixture-puuid-1"}
    with pytest.raises(ValidationError):
        TimelineSnapshot.model_validate(padded_key)


def test_normalizer_preserves_champion_kill_fields() -> None:
    result = _normalize()
    fact = next(
        fact
        for fact in result.snapshot.facts
        if isinstance(fact, ChampionKillFact) and fact.frame_index == 1 and fact.event_index == 0
    )
    assert fact.kind == "champion_kill"
    assert fact.timestamp_ms == 61_000
    assert fact.killer_id == 1
    assert fact.victim_id == 6
    assert fact.assisting_participant_ids == (2, 3)
    assert fact.position == TimelinePosition(x=4000, y=5000)
    assert fact.fact_id == "timeline:NA1:NA1_fixture:v1:frame:1:event:0"


def test_normalizer_preserves_elite_monster_kill_fields() -> None:
    result = _normalize()
    fact = next(
        fact
        for fact in result.snapshot.facts
        if isinstance(fact, EliteMonsterKillFact) and fact.event_index == 1
    )
    assert fact.kind == "elite_monster_kill"
    assert fact.timestamp_ms == 62_000
    assert fact.killer_id == 2
    assert fact.killer_team_id == 100
    assert fact.monster_type == "DRAGON"
    assert fact.monster_sub_type == "FIRE_DRAGON"
    assert fact.position == TimelinePosition(x=9800, y=4400)


def test_normalizer_preserves_building_kill_fields() -> None:
    result = _normalize()
    fact = next(
        fact
        for fact in result.snapshot.facts
        if isinstance(fact, BuildingKillFact) and fact.event_index == 2
    )
    assert fact.kind == "building_kill"
    assert fact.timestamp_ms == 63_000
    assert fact.killer_id == 3
    assert fact.team_id == 200
    assert fact.building_type == "TOWER_BUILDING"
    assert fact.lane_type == "MID_LANE"
    assert fact.tower_type == "OUTER_TURRET"
    assert fact.position == TimelinePosition(x=8955, y=8510)


def test_normalizer_preserves_four_item_event_kinds() -> None:
    result = _normalize()
    purchased = next(
        fact
        for fact in result.snapshot.facts
        if isinstance(fact, ItemEventFact) and fact.kind == "item_purchased"
    )
    sold = next(
        fact
        for fact in result.snapshot.facts
        if isinstance(fact, ItemEventFact) and fact.kind == "item_sold"
    )
    destroyed = next(
        fact
        for fact in result.snapshot.facts
        if isinstance(fact, ItemEventFact) and fact.kind == "item_destroyed"
    )
    undo = next(
        fact
        for fact in result.snapshot.facts
        if isinstance(fact, ItemEventFact) and fact.kind == "item_undo"
    )
    assert purchased.participant_id == 1
    assert purchased.item_id == 1055
    assert purchased.before_id is None
    assert purchased.after_id is None
    assert sold.participant_id == 4 and sold.item_id == 1001
    assert destroyed.participant_id == 5 and destroyed.item_id == 2003
    assert undo.participant_id == 1
    assert undo.item_id is None
    assert undo.before_id == 1055
    assert undo.after_id == 0
    assert not any(
        isinstance(fact, ItemEventFact) and "transform" in fact.kind
        for fact in result.snapshot.facts
    )


def test_normalizer_preserves_participant_state_fields() -> None:
    result = _normalize()
    fact = next(
        fact
        for fact in result.snapshot.facts
        if isinstance(fact, ParticipantStateFact)
        and fact.frame_index == 0
        and fact.participant_id == 1
    )
    assert fact.kind == "participant_state"
    assert fact.timestamp_ms == 0
    assert fact.level == 1
    assert fact.current_gold == 100
    assert fact.total_gold == 1000
    assert fact.minions_killed == 10
    assert fact.jungle_minions_killed == 1
    assert fact.xp == 200
    assert fact.position == TimelinePosition(x=100, y=200)
    assert fact.fact_id == "timeline:NA1:NA1_fixture:v1:frame:0:participant:1"


def test_normalizer_keeps_missing_optionals_none_and_preserves_zeros() -> None:
    payload = timeline_payload_with_optional_gaps()
    result = _normalize(payload, match_id="NA1_fixture_optional")
    zero_state = next(
        fact
        for fact in result.snapshot.facts
        if isinstance(fact, ParticipantStateFact)
        and fact.frame_index == 0
        and fact.participant_id == 1
    )
    assert zero_state.level == 0
    assert zero_state.current_gold == 0
    assert zero_state.total_gold == 0
    assert zero_state.minions_killed == 0
    assert zero_state.jungle_minions_killed == 0
    assert zero_state.xp == 0
    assert zero_state.position is None

    kill = next(
        fact
        for fact in result.snapshot.facts
        if isinstance(fact, ChampionKillFact) and fact.event_index == 0
    )
    assert kill.position is None
    assert kill.assisting_participant_ids == (2,)

    monster = next(fact for fact in result.snapshot.facts if isinstance(fact, EliteMonsterKillFact))
    assert monster.monster_sub_type is None
    assert monster.position is None

    building = next(fact for fact in result.snapshot.facts if isinstance(fact, BuildingKillFact))
    assert building.lane_type is None
    assert building.tower_type is None
    assert building.position is None

    undo = next(
        fact
        for fact in result.snapshot.facts
        if isinstance(fact, ItemEventFact) and fact.kind == "item_undo"
    )
    assert undo.before_id == 0
    assert undo.after_id == 0


def test_normalizer_is_deterministic_and_uses_stable_fact_ids() -> None:
    first = _normalize(copy.deepcopy(timeline_payload_for_normalizer()))
    second = _normalize(copy.deepcopy(timeline_payload_for_normalizer()))
    assert first.snapshot.model_dump(mode="json") == second.snapshot.model_dump(mode="json")
    first_bytes = json.dumps(
        first.snapshot.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    second_bytes = json.dumps(
        second.snapshot.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert first_bytes == second_bytes
    assert first.snapshot_hash == second.snapshot_hash
    assert first.snapshot_hash == hashlib.sha256(first_bytes).hexdigest()
    assert first.snapshot_hash == canonical_timeline_snapshot_hash(first.snapshot)
    assert [fact.fact_id for fact in first.snapshot.facts] == [
        fact.fact_id for fact in second.snapshot.facts
    ]
    assert any(
        fact.fact_id == "timeline:NA1:NA1_fixture:v1:frame:0:event:0"
        for fact in first.snapshot.facts
    )
    assert any(
        fact.fact_id == "timeline:NA1:NA1_fixture:v1:frame:0:participant:1"
        for fact in first.snapshot.facts
    )


def test_normalizer_fact_ids_exclude_puuids_and_result_excludes_raw_payload() -> None:
    result = _normalize()
    dumped = json.dumps(result.snapshot.model_dump(mode="json"))
    for puuid in result.snapshot.participant_puuids.values():
        assert puuid.startswith("fixture-puuid-")
        assert puuid not in "".join(fact.fact_id for fact in result.snapshot.facts)
    assert "fixture-puuid-" in dumped
    assert "participantId" not in dumped
    assert "killerId" not in dumped
    assert "assistingParticipantIds" not in dumped
    assert "monsterSubType" not in dumped
    assert "UNKNOWN_EVENT_TYPE" not in dumped
    assert "arbitrary" not in dumped
    assert "unexpectedTopLevelField" not in dumped
    assert not hasattr(result, "timeline")
    assert "raw" not in result.__dataclass_fields__


def test_normalizer_orders_participant_states_before_events_per_frame() -> None:
    result = _normalize()
    facts = result.snapshot.facts
    frame0 = [fact for fact in facts if fact.frame_index == 0]
    frame1 = [fact for fact in facts if fact.frame_index == 1]
    assert all(
        fact.frame_index <= next_fact.frame_index
        for fact, next_fact in zip(facts, facts[1:], strict=False)
    )

    frame0_states = [fact for fact in frame0 if isinstance(fact, ParticipantStateFact)]
    frame0_events = [fact for fact in frame0 if not isinstance(fact, ParticipantStateFact)]
    assert [fact.participant_id for fact in frame0_states] == list(range(1, 11))
    assert frame0 == [*frame0_states, *frame0_events]
    assert [fact.event_index for fact in frame0_events] == [0]

    frame1_states = [fact for fact in frame1 if isinstance(fact, ParticipantStateFact)]
    frame1_events = [fact for fact in frame1 if not isinstance(fact, ParticipantStateFact)]
    assert [fact.participant_id for fact in frame1_states] == list(range(1, 11))
    assert frame1 == [*frame1_states, *frame1_events]
    assert [fact.event_index for fact in frame1_events] == list(range(len(frame1_events)))


def test_normalizer_ignores_unknown_events_without_retaining_names() -> None:
    result = _normalize()
    assert result.ignored_event_count == 1
    assert result.supported_event_counts["item_purchased"] == 1
    assert result.supported_event_counts["champion_kill"] == 2
    assert result.supported_event_counts["elite_monster_kill"] == 1
    assert result.supported_event_counts["building_kill"] == 1
    assert result.supported_event_counts["item_sold"] == 1
    assert result.supported_event_counts["item_destroyed"] == 1
    assert result.supported_event_counts["item_undo"] == 1
    assert "ignored" not in result.supported_event_counts
    assert not any("unknown" in fact.kind for fact in result.snapshot.facts)
    assert "UNKNOWN_EVENT_TYPE" not in repr(result)
    assert "UNKNOWN_EVENT_TYPE" not in json.dumps(result.snapshot.model_dump(mode="json"))


def test_participant_ids_come_from_metadata_order() -> None:
    result = _normalize()
    assert result.snapshot.participant_puuids == {
        index: f"fixture-puuid-{index}" for index in range(1, 11)
    }
    assert result.snapshot.platform == Platform.NA1
    assert result.snapshot.match_id == "NA1_fixture"
    assert result.snapshot.schema_version == 1
    assert result.snapshot.frame_interval_ms == 60_000
