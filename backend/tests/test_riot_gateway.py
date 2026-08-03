import asyncio
import copy
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from app.core.errors import ApiError
from app.core.routing import Platform, Region
from app.services.riot.client import RiotHttpClient
from app.services.riot.gateway import RiotGateway
from tests.fixtures.riot_payloads import MATCH_PAYLOAD, TIMELINE_PAYLOAD


async def _fetch_timeline(
    payload: dict[str, object],
    *,
    platform: Platform = Platform.NA1,
    match_id: str = "NA1_fixture_timeline",
) -> Any:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        return await RiotGateway(
            RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
        ).get_match_timeline(platform=platform, match_id=match_id)


async def _reject_timeline(mutate: Callable[[dict[str, Any]], None]) -> ApiError:
    payload = copy.deepcopy(TIMELINE_PAYLOAD)
    mutate(payload)
    with pytest.raises(ApiError) as caught:
        await _fetch_timeline(payload)
    assert caught.value.status_code == 502
    assert caught.value.code == "RIOT_INVALID_RESPONSE"
    return caught.value


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


@pytest.mark.asyncio
async def test_gateway_validates_timeline_and_ignores_unknown_object_fields() -> None:
    """Additive Riot Timeline fields must not discard a critically valid payload."""
    timeline = await _fetch_timeline(TIMELINE_PAYLOAD)

    assert timeline.metadata.match_id == "NA1_fixture_timeline"
    assert timeline.info.frame_interval == 60_000
    assert len(timeline.info.frames) == 2
    assert len(timeline.metadata.participants) == 10
    assert timeline.metadata.participants[0] == "fixture-puuid-1"
    assert set(timeline.info.frames[0].participant_frames) == set(range(1, 11))
    assert any(event.type == "UNKNOWN_EVENT_TYPE" for event in timeline.info.frames[0].events)


@pytest.mark.asyncio
async def test_gateway_rejects_timeline_without_top_level_metadata_or_info() -> None:
    await _reject_timeline(lambda payload: payload.pop("metadata"))
    await _reject_timeline(lambda payload: payload.pop("info"))


@pytest.mark.asyncio
async def test_gateway_rejects_timeline_without_metadata_match_id() -> None:
    await _reject_timeline(lambda payload: payload["metadata"].pop("matchId"))


@pytest.mark.asyncio
async def test_gateway_rejects_timeline_with_duplicate_participant_puuids() -> None:
    await _reject_timeline(
        lambda payload: payload["metadata"].__setitem__(
            "participants",
            ["fixture-puuid-1"] * 10,
        )
    )


@pytest.mark.asyncio
async def test_gateway_maps_metadata_participant_order_to_internal_ids() -> None:
    """Metadata order is the sole source of participant IDs 1..N for frame keys."""
    timeline = await _fetch_timeline(TIMELINE_PAYLOAD)

    assert timeline.metadata.participants == tuple(
        f"fixture-puuid-{index}" for index in range(1, 11)
    )
    for participant_id, frame in timeline.info.frames[0].participant_frames.items():
        assert frame.participant_id == participant_id
        assert 1 <= participant_id <= 10


@pytest.mark.asyncio
@pytest.mark.parametrize("frame_interval", [1_000, 120_000])
async def test_gateway_accepts_frame_interval_bounds(frame_interval: int) -> None:
    payload = copy.deepcopy(TIMELINE_PAYLOAD)
    payload["info"]["frameInterval"] = frame_interval
    timeline = await _fetch_timeline(payload)
    assert timeline.info.frame_interval == frame_interval


@pytest.mark.asyncio
@pytest.mark.parametrize("frame_interval", [999, 120_001])
async def test_gateway_rejects_frame_interval_outside_bounds(frame_interval: int) -> None:
    await _reject_timeline(
        lambda payload: payload["info"].__setitem__("frameInterval", frame_interval)
    )


@pytest.mark.asyncio
async def test_gateway_rejects_negative_or_non_monotonic_frame_timestamps() -> None:
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][0].__setitem__("timestamp", -1)
    )

    def decrease_second_frame(payload: dict[str, Any]) -> None:
        payload["info"]["frames"][0]["timestamp"] = 10_000
        payload["info"]["frames"][1]["timestamp"] = 9_999

    await _reject_timeline(decrease_second_frame)


@pytest.mark.asyncio
async def test_gateway_rejects_unknown_or_mismatched_participant_frame_keys() -> None:
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][0]["participantFrames"].__setitem__(
            "99",
            {
                "participantId": 99,
                "level": 1,
                "currentGold": 0,
                "totalGold": 0,
                "minionsKilled": 0,
                "jungleMinionsKilled": 0,
                "xp": 0,
            },
        )
    )
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][0]["participantFrames"]["1"].__setitem__(
            "participantId",
            2,
        )
    )
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][0].__setitem__(
            "participantFrames",
            {
                True: {
                    "participantId": 1,
                    "level": 1,
                    "currentGold": 0,
                    "totalGold": 0,
                    "minionsKilled": 0,
                    "jungleMinionsKilled": 0,
                    "xp": 0,
                }
            },
        )
    )


@pytest.mark.asyncio
async def test_gateway_rejects_negative_participant_frame_stats() -> None:
    for field in (
        "level",
        "currentGold",
        "totalGold",
        "minionsKilled",
        "jungleMinionsKilled",
        "xp",
    ):
        await _reject_timeline(
            lambda payload, field=field: payload["info"]["frames"][0]["participantFrames"][
                "1"
            ].__setitem__(field, -1)
        )


@pytest.mark.asyncio
async def test_gateway_rejects_incomplete_or_negative_positions() -> None:
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][0]["participantFrames"]["1"].__setitem__(
            "position",
            {"x": 1},
        )
    )
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][0]["participantFrames"]["1"].__setitem__(
            "position",
            {"x": -1, "y": 1},
        )
    )


@pytest.mark.asyncio
async def test_gateway_rejects_negative_supported_event_timestamps() -> None:
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][0]["events"][0].__setitem__("timestamp", -1)
    )


@pytest.mark.asyncio
async def test_gateway_rejects_known_events_missing_critical_fields() -> None:
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][1]["events"].__setitem__(
            0,
            {"type": "CHAMPION_KILL", "timestamp": 1, "killerId": 1},
        )
    )
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][1]["events"].__setitem__(
            1,
            {"type": "ELITE_MONSTER_KILL", "timestamp": 1, "killerId": 1, "killerTeamId": 100},
        )
    )
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][1]["events"].__setitem__(
            2,
            {"type": "BUILDING_KILL", "timestamp": 1, "killerId": 1, "teamId": 200},
        )
    )
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][1]["events"].__setitem__(
            3,
            {"type": "ITEM_SOLD", "timestamp": 1, "participantId": 1},
        )
    )
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][1]["events"].__setitem__(
            5,
            {"type": "ITEM_UNDO", "timestamp": 1, "participantId": 1, "beforeId": 1},
        )
    )


@pytest.mark.asyncio
async def test_gateway_accepts_unknown_event_types_as_ignorable_input() -> None:
    timeline = await _fetch_timeline(TIMELINE_PAYLOAD)
    unknown = [
        event for event in timeline.info.frames[0].events if event.type == "UNKNOWN_EVENT_TYPE"
    ]
    assert len(unknown) == 1
    assert unknown[0].timestamp == 1_500


@pytest.mark.asyncio
async def test_gateway_rejects_duplicate_assistants_and_unknown_participant_refs() -> None:
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][1]["events"][0].__setitem__(
            "assistingParticipantIds",
            [2, 2],
        )
    )
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][1]["events"][0].__setitem__(
            "assistingParticipantIds",
            [99],
        )
    )
    await _reject_timeline(
        lambda payload: payload["info"]["frames"][1]["events"][0].__setitem__("victimId", 99)
    )


@pytest.mark.asyncio
async def test_gateway_allows_neutral_killer_id_zero_only_on_killer_fields() -> None:
    timeline = await _fetch_timeline(TIMELINE_PAYLOAD)
    neutral_kill = next(
        event
        for event in timeline.info.frames[1].events
        if event.type == "CHAMPION_KILL" and event.timestamp == 67_000
    )
    assert neutral_kill.model_dump(by_alias=True)["killerId"] == 0

    await _reject_timeline(
        lambda payload: payload["info"]["frames"][1]["events"][0].__setitem__("victimId", 0)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "expected_host"),
    [
        (Platform.NA1, "americas.api.riotgames.com"),
        (Platform.EUW1, "europe.api.riotgames.com"),
        (Platform.KR, "asia.api.riotgames.com"),
        (Platform.SG2, "sea.api.riotgames.com"),
    ],
)
async def test_gateway_gets_match_timeline_on_closed_regional_hosts(
    platform: Platform, expected_host: str
) -> None:
    seen_url = ""

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx2.Response(200, json=TIMELINE_PAYLOAD)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        timeline = await RiotGateway(
            RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
        ).get_match_timeline(platform=platform, match_id="EUW1 path/with spaces")

    assert timeline.metadata.match_id == "NA1_fixture_timeline"
    assert seen_url.startswith(f"https://{expected_host}/")
    assert seen_url.endswith("/lol/match/v5/matches/EUW1%20path%2Fwith%20spaces/timeline")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (404, "MATCH_TIMELINE_NOT_FOUND", False),
        (401, "RIOT_AUTH_FAILED", False),
        (403, "RIOT_AUTH_FAILED", False),
        (429, "RIOT_RATE_LIMITED", True),
        (503, "RIOT_UNAVAILABLE", True),
    ],
)
async def test_gateway_timeline_propagates_safe_upstream_errors(
    status_code: int, expected_code: str, retryable: bool
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if status_code == 429:
            return httpx2.Response(429, headers={"Retry-After": "30"}, json={"secret": "body"})
        return httpx2.Response(status_code, json={"secret": "body"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        with pytest.raises(ApiError) as caught:
            await RiotGateway(
                RiotHttpClient(
                    api_key="RGAPI-fake",
                    client=raw_client,
                    sleep=lambda _: asyncio.sleep(0),
                )
            ).get_match_timeline(platform=Platform.EUW1, match_id="EUW1_1")

    assert caught.value.code == expected_code
    assert caught.value.retryable is retryable
    assert "secret" not in caught.value.message
    assert "body" not in caught.value.message


@pytest.mark.asyncio
async def test_gateway_timeline_maps_connection_timeout_and_malformed_json_safely() -> None:
    def timeout_handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("boom", request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(timeout_handler)) as raw_client:
        with pytest.raises(ApiError) as caught:
            await RiotGateway(
                RiotHttpClient(
                    api_key="RGAPI-fake",
                    client=raw_client,
                    sleep=lambda _: asyncio.sleep(0),
                )
            ).get_match_timeline(platform=Platform.NA1, match_id="NA1_1")
    assert caught.value.code == "RIOT_UNAVAILABLE"
    assert "boom" not in caught.value.message

    def malformed_handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"not-json")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(malformed_handler)) as raw_client:
        with pytest.raises(ApiError) as caught:
            await RiotGateway(
                RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
            ).get_match_timeline(platform=Platform.NA1, match_id="NA1_1")
    assert caught.value.code == "RIOT_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_gateway_timeline_maps_invalid_dto_without_payload_leakage() -> None:
    invalid_payload = {"metadata": {"matchId": "NA1_1"}, "info": {"frameInterval": 60_000}}

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=invalid_payload)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as raw_client:
        with pytest.raises(ApiError) as caught:
            await RiotGateway(
                RiotHttpClient(api_key="RGAPI-fake", client=raw_client)
            ).get_match_timeline(platform=Platform.NA1, match_id="NA1_1")

    assert caught.value.code == "RIOT_INVALID_RESPONSE"
    assert "frameInterval" not in caught.value.message
    assert "NA1_1" not in caught.value.message
