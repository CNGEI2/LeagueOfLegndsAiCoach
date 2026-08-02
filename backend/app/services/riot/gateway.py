from urllib.parse import quote

from app.core.routing import Platform, Region, regional_host_for, routes_for
from app.services.riot.client import RiotHttpClient
from app.services.riot.dto import (
    AccountDto,
    MatchDto,
    SummonerDto,
    validate_match_ids,
    validate_riot_model,
)


class RiotGateway:
    def __init__(self, client: RiotHttpClient) -> None:
        self._client = client

    async def get_account_by_puuid(self, *, platform: Platform, puuid: str) -> AccountDto:
        host = routes_for(platform).regional_host
        payload = await self._client.get_json(
            host=host,
            path=f"/riot/account/v1/accounts/by-puuid/{quote(puuid, safe='')}",
            params=None,
            not_found_code="PLAYER_NOT_FOUND",
        )
        return validate_riot_model(AccountDto, payload)

    async def get_account_by_riot_id(
        self, *, platform: Platform, game_name: str, tag_line: str
    ) -> AccountDto:
        return await self.get_account_by_riot_id_in_region(
            region=routes_for(platform).region,
            game_name=game_name,
            tag_line=tag_line,
        )

    async def get_account_by_riot_id_in_region(
        self, *, region: Region, game_name: str, tag_line: str
    ) -> AccountDto:
        host = regional_host_for(region)
        path = (
            "/riot/account/v1/accounts/by-riot-id/"
            f"{quote(game_name, safe='')}/{quote(tag_line, safe='')}"
        )
        payload = await self._client.get_json(
            host=host, path=path, params=None, not_found_code="PLAYER_NOT_FOUND"
        )
        return validate_riot_model(AccountDto, payload)

    async def get_summoner_by_puuid(self, *, platform: Platform, puuid: str) -> SummonerDto:
        host = routes_for(platform).platform_host
        payload = await self._client.get_json(
            host=host,
            path=f"/lol/summoner/v4/summoners/by-puuid/{quote(puuid, safe='')}",
            params=None,
            not_found_code="PLAYER_NOT_FOUND",
        )
        return validate_riot_model(SummonerDto, payload)

    async def get_match_ids(self, *, platform: Platform, puuid: str, count: int) -> tuple[str, ...]:
        host = routes_for(platform).regional_host
        payload = await self._client.get_json(
            host=host,
            path=f"/lol/match/v5/matches/by-puuid/{quote(puuid, safe='')}/ids",
            params={"start": 0, "count": count},
            not_found_code="PLAYER_NOT_FOUND",
        )
        return validate_match_ids(payload, max_count=count)

    async def get_match(self, *, platform: Platform, match_id: str) -> MatchDto:
        host = routes_for(platform).regional_host
        payload = await self._client.get_json(
            host=host,
            path=f"/lol/match/v5/matches/{quote(match_id, safe='')}",
            params=None,
            not_found_code="MATCH_NOT_FOUND",
        )
        return validate_riot_model(MatchDto, payload)
