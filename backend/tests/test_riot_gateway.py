import asyncio

import httpx2
import pytest

from app.core.errors import ApiError
from app.core.routing import Platform, Region
from app.services.riot.client import RiotHttpClient
from app.services.riot.gateway import RiotGateway
from tests.fixtures.riot_payloads import MATCH_PAYLOAD


@pytest.mark.asyncio
async def test_gateway_gets_account_by_puuid_on_regional_route() -> None:
    """Direct player links resolve accounts through Riot's regional route."""
    seen_url = ""

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx2.Response(
            200,
            json={"puuid": "puuid-1", "gameName": "PlayerName", "tagLine": "1115"},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        gateway = RiotGateway(RiotHttpClient(api_key="RGAPI-fake", client=raw_client))
        account = await gateway.get_account_by_puuid(platform=Platform.NA1, puuid="puuid-1")

    assert account.game_name == "PlayerName"
    assert seen_url.startswith("https://americas.api.riotgames.com/")
    assert seen_url.endswith("/riot/account/v1/accounts/by-puuid/puuid-1")


@pytest.mark.asyncio
async def test_gateway_uses_independent_tag_line_and_regional_account_route() -> None:
    """A tag line must remain distinct from the game name and use the regional host."""
    seen_url = ""

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx2.Response(
            200,
            json={"puuid": "puuid-1", "gameName": "Player Name", "tagLine": "1115"},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        gateway = RiotGateway(RiotHttpClient(api_key="RGAPI-fake", client=raw_client))
        account = await gateway.get_account_by_riot_id(
            platform=Platform.NA1,
            game_name="Player Name",
            tag_line="1115",
        )

    assert account.tag_line == "1115"
    assert seen_url.startswith("https://americas.api.riotgames.com/")
    assert "Player%20Name/1115" in seen_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("region", "expected_host"),
    [
        (Region.AMERICAS, "americas.api.riotgames.com"),
        (Region.ASIA, "asia.api.riotgames.com"),
        (Region.EUROPE, "europe.api.riotgames.com"),
        (Region.SEA, "sea.api.riotgames.com"),
    ],
)
async def test_gateway_gets_riot_id_from_selected_region_with_encoded_path(
    region: Region, expected_host: str
) -> None:
    """Changing the regional route or losing percent encoding misaddresses Account-V1."""
    seen_url = ""

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx2.Response(
            200,
            json={"puuid": "puuid-1", "gameName": "Game /#", "tagLine": "Tag #"},
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        account = await RiotGateway(
            RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
        ).get_account_by_riot_id_in_region(
            region=region,
            game_name="Game /#",
            tag_line="Tag #",
        )

    assert account.puuid == "puuid-1"
    assert seen_url.startswith(f"https://{expected_host}/")
    assert "/by-riot-id/Game%20%2F%23/Tag%20%23" in seen_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (404, "PLAYER_NOT_FOUND"),
        (401, "RIOT_AUTH_FAILED"),
        (429, "RIOT_RATE_LIMITED"),
        (503, "RIOT_UNAVAILABLE"),
    ],
)
async def test_gateway_region_account_lookup_propagates_safe_upstream_errors(
    status_code: int, expected_code: str
) -> None:
    """Regional lookup must retain Account-V1's not-found and transient error contract."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status_code, json={})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        with pytest.raises(ApiError) as caught:
            await RiotGateway(
                RiotHttpClient(
                    api_key="RGAPI-fake",
                    client=raw_client,
                    sleep=lambda _: asyncio.sleep(0),
                )
            ).get_account_by_riot_id_in_region(
                region=Region.EUROPE,
                game_name="Player",
                tag_line="EUW",
            )

    assert caught.value.code == expected_code


@pytest.mark.asyncio
async def test_gateway_region_account_lookup_rejects_invalid_account_payload() -> None:
    """A malformed Account-V1 result must not become a platform-detection identity."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"puuid": "puuid-1", "gameName": "Player"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        with pytest.raises(ApiError) as caught:
            await RiotGateway(
                RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
            ).get_account_by_riot_id_in_region(
                region=Region.ASIA,
                game_name="Player",
                tag_line="KR",
            )

    assert caught.value.code == "RIOT_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_gateway_uses_platform_host_for_summoner_lookup() -> None:
    """Summoner-V4 belongs to the platform route rather than the regional route."""
    seen_url = ""

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx2.Response(
            200,
            json={
                "id": "summoner-id",
                "accountId": "account-id",
                "puuid": "puuid-1",
                "profileIconId": 23,
                "summonerLevel": 99,
                "revisionDate": 1720000000000,
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        summoner = await RiotGateway(
            RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
        ).get_summoner_by_puuid(platform=Platform.NA1, puuid="puuid-1")

    assert summoner.profile_icon_id == 23
    assert seen_url.startswith("https://na1.api.riotgames.com/")


@pytest.mark.asyncio
async def test_gateway_accepts_current_summoner_payload_without_legacy_identity_fields() -> None:
    """Requiring retired legacy IDs would reject the current successful Summoner-V4 shape."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "profileIconId": 23,
                "puuid": "sanitized-puuid",
                "revisionDate": 1720000000000,
                "summonerLevel": 99,
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        summoner = await RiotGateway(
            RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
        ).get_summoner_by_puuid(platform=Platform.NA1, puuid="sanitized-puuid")

    assert summoner.puuid == "sanitized-puuid"
    assert summoner.profile_icon_id == 23
    assert summoner.summoner_level == 99
    assert summoner.revision_date == 1720000000000


@pytest.mark.asyncio
async def test_gateway_rejects_summoner_without_required_revision_date() -> None:
    """Making revisionDate optional would weaken the current response contract."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "profileIconId": 23,
                "puuid": "sanitized-puuid",
                "summonerLevel": 99,
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        with pytest.raises(ApiError) as caught:
            await RiotGateway(
                RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
            ).get_summoner_by_puuid(platform=Platform.NA1, puuid="sanitized-puuid")

    assert caught.value.code == "RIOT_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_gateway_requests_recent_match_ids_from_regional_route() -> None:
    """Match-V5 requires the regional endpoint and explicit start/count pagination."""
    seen_url = ""

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx2.Response(200, json=["NA1_1", "NA1_2"])

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        match_ids = await RiotGateway(
            RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
        ).get_match_ids(platform=Platform.NA1, puuid="puuid-1", count=10)

    assert match_ids == ("NA1_1", "NA1_2")
    assert seen_url.startswith("https://americas.api.riotgames.com/")
    assert seen_url.endswith("?start=0&count=10")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "count"),
    [(["NA1_1", 2], 10), (["NA1_1", "NA1_2"], 1)],
)
async def test_gateway_rejects_non_string_or_excess_match_ids(
    payload: list[str | int], count: int
) -> None:
    """Coercing arbitrary match-id values risks creating invalid downstream requests."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        with pytest.raises(ApiError) as caught:
            await RiotGateway(
                RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
            ).get_match_ids(platform=Platform.NA1, puuid="puuid-1", count=count)

    assert caught.value.code == "RIOT_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_gateway_validates_nested_match_data_and_ignores_unknown_fields() -> None:
    """Non-critical omissions and extra upstream fields must not discard a valid match."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=MATCH_PAYLOAD)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        match = await RiotGateway(
            RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
        ).get_match(platform=Platform.NA1, match_id="NA1_123456789")

    participant = match.info.participants[0]
    assert match.metadata.match_id == "NA1_123456789"
    assert match.info.game_creation == 1720000000000
    assert participant.team_position == "MIDDLE"
    assert participant.item3 is None


@pytest.mark.asyncio
async def test_gateway_rejects_match_without_critical_metadata_match_id() -> None:
    """A match lacking its identity must not be normalized as a valid match."""
    invalid_payload = dict(MATCH_PAYLOAD)
    invalid_payload["metadata"] = {"participants": ["puuid-1"]}

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=invalid_payload)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        with pytest.raises(ApiError) as caught:
            await RiotGateway(RiotHttpClient(api_key="RGAPI-fake", client=raw_client)).get_match(
                platform=Platform.NA1, match_id="NA1_123"
            )

    assert caught.value.status_code == 502
    assert caught.value.code == "RIOT_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_gateway_rejects_match_without_critical_metadata_participants() -> None:
    """A match identity roster is required even when the match ID exists."""
    invalid_payload = dict(MATCH_PAYLOAD)
    invalid_payload["metadata"] = {"matchId": "NA1_123"}

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=invalid_payload)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        with pytest.raises(ApiError) as caught:
            await RiotGateway(RiotHttpClient(api_key="RGAPI-fake", client=raw_client)).get_match(
                platform=Platform.NA1, match_id="NA1_123"
            )

    assert caught.value.status_code == 502
    assert caught.value.code == "RIOT_INVALID_RESPONSE"
