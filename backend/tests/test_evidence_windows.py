from __future__ import annotations

from app.core.routing import Platform
from app.services.evidence.windows import EvidenceWindowPlanner
from app.services.timelines.domain import (
    BuildingKillFact,
    ChampionKillFact,
    EliteMonsterKillFact,
    ItemEventFact,
    ParticipantStateFact,
    TimelinePosition,
)

SELECTED = 1
TEAM = 100
ENEMY = 6
ENEMY_TEAM = 200
MATCH_DURATION = 1_800_000
PLATFORM = Platform.NA1
MATCH_ID = "NA1_fixture"


def _kill(
    *,
    fact_id: str,
    timestamp_ms: int,
    killer_id: int,
    victim_id: int,
    assistants: tuple[int, ...] = (),
) -> ChampionKillFact:
    return ChampionKillFact(
        fact_id=fact_id,
        kind="champion_kill",
        timestamp_ms=timestamp_ms,
        frame_index=1,
        event_index=0,
        killer_id=killer_id,
        victim_id=victim_id,
        assisting_participant_ids=assistants,
        position=TimelinePosition(x=1, y=1),
    )


def _monster(
    *,
    fact_id: str,
    timestamp_ms: int,
    killer_id: int,
    killer_team_id: int,
) -> EliteMonsterKillFact:
    return EliteMonsterKillFact(
        fact_id=fact_id,
        kind="elite_monster_kill",
        timestamp_ms=timestamp_ms,
        frame_index=1,
        event_index=0,
        killer_id=killer_id,
        killer_team_id=killer_team_id,
        monster_type="DRAGON",
        monster_sub_type="FIRE_DRAGON",
        position=None,
    )


def _building(
    *,
    fact_id: str,
    timestamp_ms: int,
    killer_id: int,
    team_id: int,
) -> BuildingKillFact:
    return BuildingKillFact(
        fact_id=fact_id,
        kind="building_kill",
        timestamp_ms=timestamp_ms,
        frame_index=1,
        event_index=0,
        killer_id=killer_id,
        team_id=team_id,
        building_type="TOWER_BUILDING",
        lane_type="MID_LANE",
        tower_type="OUTER_TURRET",
        position=None,
    )


def _plan(facts, *, match_duration_ms: int = MATCH_DURATION):
    return EvidenceWindowPlanner().plan(
        platform=PLATFORM,
        match_id=MATCH_ID,
        schema_version=1,
        match_duration_ms=match_duration_ms,
        selected_participant_id=SELECTED,
        selected_team_id=TEAM,
        participant_team_ids={
            1: 100,
            2: 100,
            3: 100,
            4: 100,
            5: 100,
            6: 200,
            7: 200,
            8: 200,
            9: 200,
            10: 200,
        },
        facts=facts,
    )


def test_selected_killer_and_assistant_create_combat_windows() -> None:
    plan = _plan(
        (
            _kill(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:0",
                timestamp_ms=60_000,
                killer_id=SELECTED,
                victim_id=ENEMY,
            ),
            _kill(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:1",
                timestamp_ms=90_000,
                killer_id=2,
                victim_id=ENEMY,
                assistants=(SELECTED, 3),
            ),
        )
    )
    assert len(plan.windows) == 2
    assert plan.windows[0].start_ms == 48_000
    assert plan.windows[0].end_ms == 68_000
    assert plan.windows[0].categories == ("combat_context",)
    assert plan.windows[1].start_ms == 78_000
    assert plan.windows[1].end_ms == 98_000
    assert plan.windows[1].categories == ("combat_context",)


def test_selected_victim_creates_death_window() -> None:
    plan = _plan(
        (
            _kill(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:0",
                timestamp_ms=60_000,
                killer_id=ENEMY,
                victim_id=SELECTED,
            ),
        )
    )
    assert len(plan.windows) == 1
    assert plan.windows[0].start_ms == 45_000
    assert plan.windows[0].end_ms == 70_000
    assert plan.windows[0].categories == ("death_context",)


def test_selected_team_objective_and_building_windows_require_explicit_mapping() -> None:
    plan = _plan(
        (
            _monster(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:0",
                timestamp_ms=100_000,
                killer_id=2,
                killer_team_id=TEAM,
            ),
            _building(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:1",
                timestamp_ms=160_000,
                killer_id=SELECTED,
                team_id=ENEMY_TEAM,
            ),
        )
    )
    assert len(plan.windows) == 2
    assert plan.windows[0].start_ms == 80_000
    assert plan.windows[0].end_ms == 110_000
    assert plan.windows[0].categories == ("objective_context",)
    assert plan.windows[1].start_ms == 140_000
    assert plan.windows[1].end_ms == 170_000
    assert plan.windows[1].categories == ("building_context",)


def test_items_participant_state_unrelated_and_killer_zero_create_no_windows() -> None:
    plan = _plan(
        (
            ItemEventFact(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:0:event:0",
                kind="item_purchased",
                timestamp_ms=1_000,
                frame_index=0,
                event_index=0,
                participant_id=SELECTED,
                item_id=1055,
            ),
            ParticipantStateFact(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:0:participant:1",
                kind="participant_state",
                timestamp_ms=0,
                frame_index=0,
                participant_id=SELECTED,
                level=1,
                current_gold=100,
                total_gold=100,
                minions_killed=0,
                jungle_minions_killed=0,
                xp=0,
                position=None,
            ),
            _kill(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:0",
                timestamp_ms=60_000,
                killer_id=2,
                victim_id=ENEMY,
                assistants=(3,),
            ),
            _monster(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:1",
                timestamp_ms=80_000,
                killer_id=0,
                killer_team_id=TEAM,
            ),
            _building(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:2",
                timestamp_ms=90_000,
                killer_id=0,
                team_id=ENEMY_TEAM,
            ),
            _monster(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:3",
                timestamp_ms=100_000,
                killer_id=ENEMY,
                killer_team_id=ENEMY_TEAM,
            ),
        )
    )
    assert plan.windows == ()
    assert plan.truncated is False
    assert plan.total_window_count == 0


def test_objective_windows_require_roster_team_consistent_with_killer_team_id() -> None:
    conflicting = _plan(
        (
            _monster(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:0",
                timestamp_ms=100_000,
                killer_id=ENEMY,
                killer_team_id=TEAM,
            ),
        )
    )
    assert conflicting.windows == ()
    assert conflicting.total_window_count == 0

    missing_roster = EvidenceWindowPlanner().plan(
        platform=PLATFORM,
        match_id=MATCH_ID,
        schema_version=1,
        match_duration_ms=MATCH_DURATION,
        selected_participant_id=SELECTED,
        selected_team_id=TEAM,
        participant_team_ids={SELECTED: TEAM},
        facts=(
            _monster(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:1",
                timestamp_ms=120_000,
                killer_id=2,
                killer_team_id=TEAM,
            ),
        ),
    )
    assert missing_roster.windows == ()

    ally_consistent = _plan(
        (
            _monster(
                fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:2",
                timestamp_ms=140_000,
                killer_id=2,
                killer_team_id=TEAM,
            ),
        )
    )
    assert len(ally_consistent.windows) == 1
    assert ally_consistent.windows[0].categories == ("objective_context",)


def test_windows_are_clamped_merged_sorted_and_capped() -> None:
    early = _kill(
        fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:0",
        timestamp_ms=5_000,
        killer_id=SELECTED,
        victim_id=ENEMY,
    )
    overlapping_a = _kill(
        fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:1",
        timestamp_ms=60_000,
        killer_id=SELECTED,
        victim_id=ENEMY,
    )
    overlapping_b = _kill(
        fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:2",
        timestamp_ms=65_000,
        killer_id=ENEMY,
        victim_id=SELECTED,
    )
    gap_left = _kill(
        fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:3",
        timestamp_ms=200_000,
        killer_id=SELECTED,
        victim_id=ENEMY,
    )
    gap_right = _kill(
        fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:4",
        timestamp_ms=200_000 + 12_000 + 8_000 + 1,
        killer_id=SELECTED,
        victim_id=ENEMY,
    )
    late = _kill(
        fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:5",
        timestamp_ms=MATCH_DURATION - 1_000,
        killer_id=SELECTED,
        victim_id=ENEMY,
    )
    plan = _plan((early, overlapping_a, overlapping_b, gap_left, gap_right, late))

    assert plan.windows[0].start_ms == 0
    assert plan.windows[0].end_ms == 13_000
    merged = next(
        window
        for window in plan.windows
        if "timeline:NA1:NA1_fixture:v1:frame:1:event:1" in window.trigger_fact_ids
    )
    assert merged.start_ms == 48_000
    assert merged.end_ms == 75_000
    assert merged.categories == ("combat_context", "death_context")
    assert merged.trigger_fact_ids == (
        "timeline:NA1:NA1_fixture:v1:frame:1:event:1",
        "timeline:NA1:NA1_fixture:v1:frame:1:event:2",
    )
    assert any(window.start_ms == 188_000 and window.end_ms == 208_000 for window in plan.windows)
    assert any(window.start_ms == 208_001 and window.end_ms == 228_001 for window in plan.windows)
    assert plan.windows[-1].end_ms == MATCH_DURATION
    assert [window.window_id for window in plan.windows] == [
        f"evidence-window:NA1:NA1_fixture:v1:{index}" for index in range(len(plan.windows))
    ]
    assert "fixture-puuid" not in "".join(window.window_id for window in plan.windows)


def test_planner_returns_at_most_64_windows_with_truncation_metadata() -> None:
    facts = tuple(
        _kill(
            fact_id=f"timeline:NA1:NA1_fixture:v1:frame:1:event:{index}",
            timestamp_ms=50_000 + index * 40_000,
            killer_id=SELECTED,
            victim_id=ENEMY,
        )
        for index in range(65)
    )
    plan = _plan(facts, match_duration_ms=3_000_000)
    assert len(plan.windows) == 64
    assert plan.truncated is True
    assert plan.total_window_count == 65
    assert plan.windows[0].window_id == "evidence-window:NA1:NA1_fixture:v1:0"
    assert plan.windows[-1].window_id == "evidence-window:NA1:NA1_fixture:v1:63"
