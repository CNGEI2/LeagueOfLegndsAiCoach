from dataclasses import dataclass

from app.core.errors import ApiError, invalid_riot_id
from app.core.normalization import lookup_key
from app.core.routing import Platform
from app.schemas.domain import PlayerProfile
from app.services.riot.dto import AccountDto, SummonerDto


@dataclass(frozen=True)
class ParsedRiotId:
    game_name: str
    tag_line: str
    game_name_key: str
    tag_line_key: str


def parse_riot_id(value: str) -> ParsedRiotId:
    normalized = value.strip()
    game_name, separator, tag_line = normalized.rpartition("#")
    if not separator or not 1 <= len(game_name) <= 32 or not 1 <= len(tag_line) <= 16:
        raise invalid_riot_id()
    return ParsedRiotId(
        game_name=game_name,
        tag_line=tag_line,
        game_name_key=lookup_key(game_name),
        tag_line_key=lookup_key(tag_line),
    )


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
