from datetime import UTC, datetime

from app.core.errors import ApiError
from app.core.routing import Platform
from app.schemas.domain import MatchSnapshot, ParticipantSnapshot
from app.services.riot.dto import MatchDto, ParticipantDto

_ALLOWED_ROLES = frozenset({"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"})


def normalize_match(dto: MatchDto, platform: Platform) -> MatchSnapshot:
    """Convert a validated Match-V5 DTO while protecting public data invariants."""
    participants = dto.info.participants
    if (
        not dto.metadata.match_id.startswith(f"{platform.value}_")
        or not participants
        or _has_duplicate_puuids(participants)
    ):
        raise _invalid_response()

    roster = dto.metadata.participants
    participant_puuids = tuple(participant.puuid for participant in participants)
    if len(roster) != len(participant_puuids) or set(roster) != set(participant_puuids):
        raise _invalid_response()

    try:
        started_at = datetime.fromtimestamp(dto.info.game_creation / 1000, tz=UTC)
    except (OSError, OverflowError, ValueError):
        raise _invalid_response() from None

    return MatchSnapshot(
        match_id=dto.metadata.match_id,
        platform=platform,
        queue_id=dto.info.queue_id,
        game_version=dto.info.game_version,
        started_at=started_at,
        duration_seconds=dto.info.game_duration,
        participants=tuple(_normalize_participant(participant) for participant in participants),
    )


def normalize_item_ids(participant: ParticipantDto) -> tuple[int, ...]:
    values = (
        participant.item0,
        participant.item1,
        participant.item2,
        participant.item3,
        participant.item4,
        participant.item5,
        participant.item6,
    )
    return tuple(value for value in values if value is not None and value > 0)


def normalized_role(team_position: str | None) -> str | None:
    return team_position if team_position in _ALLOWED_ROLES else None


def supports_standard_detail(snapshot: MatchSnapshot) -> bool:
    """Return whether the snapshot is structurally a standard two-team 5v5 match."""
    if len(snapshot.participants) != 10:
        return False
    team_ids = {participant.team_id for participant in snapshot.participants}
    return team_ids == {100, 200} and all(
        sum(participant.team_id == team_id for participant in snapshot.participants) == 5
        for team_id in team_ids
    )


def _normalize_participant(participant: ParticipantDto) -> ParticipantSnapshot:
    lane_cs = participant.total_minions_killed
    jungle_cs = participant.neutral_minions_killed
    cs = lane_cs + jungle_cs if lane_cs is not None and jungle_cs is not None else None
    return ParticipantSnapshot(
        puuid=participant.puuid,
        team_id=participant.team_id,
        champion_id=participant.champion_id,
        role=normalized_role(participant.team_position),
        won=participant.win,
        kills=participant.kills,
        deaths=participant.deaths,
        assists=participant.assists,
        cs=cs,
        gold_earned=participant.gold_earned,
        damage_to_champions=participant.total_damage_dealt_to_champions,
        vision_score=participant.vision_score,
        item_ids=normalize_item_ids(participant),
    )


def _has_duplicate_puuids(participants: tuple[ParticipantDto, ...]) -> bool:
    puuids = tuple(participant.puuid for participant in participants)
    return len(set(puuids)) != len(puuids)


def _invalid_response() -> ApiError:
    return ApiError(
        status_code=502,
        code="RIOT_INVALID_RESPONSE",
        message="Riot returned an invalid response.",
        retryable=False,
    )
