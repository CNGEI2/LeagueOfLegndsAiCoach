import httpx2
import pytest

from app.core.errors import ApiError
from app.core.routing import Platform
from app.services.riot.client import RiotHttpClient
from app.services.riot.gateway import RiotGateway
from tests.fixtures.riot_payloads import MATCH_PAYLOAD


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
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        summoner = await RiotGateway(
            RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
        ).get_summoner_by_puuid(platform=Platform.NA1, puuid="puuid-1")

    assert summoner.profile_icon_id == 23
    assert seen_url.startswith("https://na1.api.riotgames.com/")


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
        ).get_match(platform=Platform.NA1, match_id="NA1_123")

    participant = match.info.participants[0]
    assert match.metadata.match_id == "NA1_123"
    assert match.info.game_creation == 1720000000000
    assert participant.team_position == "MIDDLE"
    assert participant.item0 is None


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
