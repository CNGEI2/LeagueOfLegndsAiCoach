from app.core.errors import ApiError
from app.core.routing import Platform
from app.schemas.domain import PlayerProfile
from app.services.riot.dto import AccountDto, SummonerDto


def normalize_player(
    account: AccountDto, summoner: SummonerDto, platform: Platform
) -> PlayerProfile:
    """Convert matching Riot identity records into the public player profile."""
    if account.puuid != summoner.puuid:
        raise _invalid_response()
    return PlayerProfile(
        puuid=account.puuid,
        game_name=account.game_name,
        tag_line=account.tag_line,
        platform=platform,
        summoner_level=summoner.summoner_level,
        profile_icon_id=summoner.profile_icon_id,
    )


def _invalid_response() -> ApiError:
    return ApiError(
        status_code=502,
        code="RIOT_INVALID_RESPONSE",
        message="Riot returned an invalid response.",
        retryable=False,
    )
