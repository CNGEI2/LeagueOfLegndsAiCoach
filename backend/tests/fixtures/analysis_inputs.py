from datetime import UTC, datetime

from app.core.routing import Platform
from app.schemas.domain import MatchSnapshot, ParticipantSnapshot
from app.services.timelines.domain import (
    BuildingKillFact,
    ChampionKillFact,
    EliteMonsterKillFact,
    TimelineSnapshot,
)

SELECTED_PUUID = "selected"
MATCH_ID = "NA1_ANALYSIS_FIXTURE"
DURATION_SECONDS = 1800

BLUE_ROLES: tuple[tuple[str, str], ...] = (
    ("blue-top", "TOP"),
    ("blue-jungle", "JUNGLE"),
    (SELECTED_PUUID, "MIDDLE"),
    ("blue-bottom", "BOTTOM"),
    ("blue-support", "UTILITY"),
)
RED_ROLES: tuple[tuple[str, str], ...] = (
    ("red-top", "TOP"),
    ("red-jungle", "JUNGLE"),
    ("red-mid", "MIDDLE"),
    ("red-bottom", "BOTTOM"),
    ("red-support", "UTILITY"),
)

_BLUE_STATS: dict[str, dict[str, int]] = {
    "blue-top": {
        "kills": 2,
        "deaths": 3,
        "assists": 1,
        "cs": 180,
        "gold_earned": 8000,
        "damage_to_champions": 5000,
        "vision_score": 20,
    },
    "blue-jungle": {
        "kills": 3,
        "deaths": 2,
        "assists": 4,
        "cs": 180,
        "gold_earned": 8500,
        "damage_to_champions": 4000,
        "vision_score": 25,
    },
    SELECTED_PUUID: {
        "kills": 4,
        "deaths": 1,
        "assists": 2,
        "cs": 210,
        "gold_earned": 9000,
        "damage_to_champions": 6000,
        "vision_score": 30,
    },
    "blue-bottom": {
        "kills": 5,
        "deaths": 4,
        "assists": 3,
        "cs": 240,
        "gold_earned": 10000,
        "damage_to_champions": 8000,
        "vision_score": 15,
    },
    "blue-support": {
        "kills": 1,
        "deaths": 5,
        "assists": 8,
        "cs": 30,
        "gold_earned": 7000,
        "damage_to_champions": 2000,
        "vision_score": 60,
    },
}
_RED_STATS: dict[str, dict[str, int]] = {
    "red-top": {
        "kills": 3,
        "deaths": 4,
        "assists": 2,
        "cs": 170,
        "gold_earned": 7800,
        "damage_to_champions": 4800,
        "vision_score": 18,
    },
    "red-jungle": {
        "kills": 4,
        "deaths": 3,
        "assists": 5,
        "cs": 160,
        "gold_earned": 8200,
        "damage_to_champions": 3900,
        "vision_score": 22,
    },
    "red-mid": {
        "kills": 3,
        "deaths": 2,
        "assists": 3,
        "cs": 150,
        "gold_earned": 7500,
        "damage_to_champions": 4500,
        "vision_score": 18,
    },
    "red-bottom": {
        "kills": 6,
        "deaths": 5,
        "assists": 2,
        "cs": 250,
        "gold_earned": 11000,
        "damage_to_champions": 9000,
        "vision_score": 12,
    },
    "red-support": {
        "kills": 0,
        "deaths": 6,
        "assists": 9,
        "cs": 25,
        "gold_earned": 6800,
        "damage_to_champions": 1800,
        "vision_score": 55,
    },
}


def _participant(
    puuid: str,
    *,
    team_id: int,
    role: str,
    won: bool,
    stats: dict[str, int],
) -> ParticipantSnapshot:
    return ParticipantSnapshot(
        puuid=puuid,
        team_id=team_id,
        champion_id=103,
        role=role,
        won=won,
        kills=stats["kills"],
        deaths=stats["deaths"],
        assists=stats["assists"],
        cs=stats["cs"],
        gold_earned=stats["gold_earned"],
        damage_to_champions=stats["damage_to_champions"],
        vision_score=stats["vision_score"],
        item_ids=(1055, 3006),
    )


def standard_analysis_match() -> MatchSnapshot:
    blue = tuple(
        _participant(puuid, team_id=100, role=role, won=True, stats=_BLUE_STATS[puuid])
        for puuid, role in BLUE_ROLES
    )
    red = tuple(
        _participant(puuid, team_id=200, role=role, won=False, stats=_RED_STATS[puuid])
        for puuid, role in RED_ROLES
    )
    return MatchSnapshot(
        match_id=MATCH_ID,
        platform=Platform.NA1,
        queue_id=420,
        game_version="16.15.1",
        started_at=datetime(2026, 8, 1, 12, tzinfo=UTC),
        duration_seconds=DURATION_SECONDS,
        participants=blue + red,
    )


def replace_participant(
    match: MatchSnapshot, puuid: str, **updates: object
) -> MatchSnapshot:
    participants = tuple(
        participant.model_copy(update=updates) if participant.puuid == puuid else participant
        for participant in match.participants
    )
    return match.model_copy(update={"participants": participants})


def toggle_won(match: MatchSnapshot) -> MatchSnapshot:
    participants = tuple(
        participant.model_copy(update={"won": not participant.won})
        for participant in match.participants
    )
    return match.model_copy(update={"participants": participants})


def standard_analysis_timeline() -> TimelineSnapshot:
    participant_puuids = {
        index: puuid
        for index, (puuid, _role) in enumerate((*BLUE_ROLES, *RED_ROLES), start=1)
    }
    return TimelineSnapshot(
        platform=Platform.NA1,
        match_id=MATCH_ID,
        schema_version=1,
        frame_interval_ms=60_000,
        participant_puuids=participant_puuids,
        facts=(
            ChampionKillFact(
                fact_id="timeline:champion_kill:ignored",
                kind="champion_kill",
                timestamp_ms=60_000,
                frame_index=1,
                event_index=0,
                killer_id=3,
                victim_id=8,
                assisting_participant_ids=(2,),
                position=None,
            ),
            EliteMonsterKillFact(
                fact_id="timeline:elite_monster:1",
                kind="elite_monster_kill",
                timestamp_ms=120_000,
                frame_index=2,
                event_index=0,
                killer_id=3,
                killer_team_id=100,
                monster_type="DRAGON",
                monster_sub_type="FIRE_DRAGON",
                position=None,
            ),
            BuildingKillFact(
                fact_id="timeline:building:2",
                kind="building_kill",
                timestamp_ms=180_000,
                frame_index=3,
                event_index=0,
                killer_id=3,
                team_id=100,
                building_type="TOWER_BUILDING",
                lane_type="MID_LANE",
                tower_type="OUTER_TURRET",
                position=None,
            ),
            BuildingKillFact(
                fact_id="timeline:building:team",
                kind="building_kill",
                timestamp_ms=240_000,
                frame_index=4,
                event_index=0,
                killer_id=0,
                team_id=100,
                building_type="TOWER_BUILDING",
                lane_type="BOT_LANE",
                tower_type="OUTER_TURRET",
                position=None,
            ),
            EliteMonsterKillFact(
                fact_id="timeline:elite_monster:other",
                kind="elite_monster_kill",
                timestamp_ms=300_000,
                frame_index=5,
                event_index=0,
                killer_id=8,
                killer_team_id=200,
                monster_type="RIFTHERALD",
                monster_sub_type=None,
                position=None,
            ),
        ),
    )
