from app.core.errors import ApiError
from app.schemas.domain import MatchSnapshot
from app.services.timelines.domain import TimelineSnapshot


def join_match_timeline_rosters(
    *,
    match: MatchSnapshot,
    timeline: TimelineSnapshot,
    selected_puuid: str,
) -> tuple[dict[int, int], int, int]:
    match_teams_by_puuid: dict[str, int] = {}
    for participant in match.participants:
        if participant.puuid in match_teams_by_puuid:
            raise invalid_roster()
        match_teams_by_puuid[participant.puuid] = participant.team_id

    timeline_puuids = list(timeline.participant_puuids.values())
    if len(timeline_puuids) != len(set(timeline_puuids)):
        raise invalid_roster()
    if set(timeline_puuids) != set(match_teams_by_puuid):
        raise invalid_roster()

    participant_team_ids = {
        participant_id: match_teams_by_puuid[puuid]
        for participant_id, puuid in timeline.participant_puuids.items()
    }
    selected_ids = [
        participant_id
        for participant_id, puuid in timeline.participant_puuids.items()
        if puuid == selected_puuid
    ]
    if len(selected_ids) != 1:
        raise ApiError(
            status_code=404,
            code="PLAYER_NOT_IN_MATCH",
            message="The selected player did not participate in this match.",
            retryable=False,
        )
    selected_participant_id = selected_ids[0]
    return (
        participant_team_ids,
        selected_participant_id,
        participant_team_ids[selected_participant_id],
    )


def invalid_roster() -> ApiError:
    return ApiError(
        status_code=502,
        code="RIOT_INVALID_RESPONSE",
        message="Riot returned an invalid response.",
        retryable=False,
    )
