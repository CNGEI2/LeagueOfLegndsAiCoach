import asyncio
import logging

import httpx2
import pytest

from app.core.errors import ApiError
from app.services.riot.client import RiotHttpClient


@pytest.mark.asyncio
async def test_riot_client_sends_server_only_token() -> None:
    """A missing header would prevent authenticated Riot requests."""
    seen_header = ""

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal seen_header
        seen_header = request.headers["X-Riot-Token"]
        return httpx2.Response(200, json={"puuid": "p"})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
        client = RiotHttpClient(api_key="RGAPI-fake", client=transport_client)
        body = await client.get_json(
            host="americas.api.riotgames.com",
            path="/riot/account/v1/accounts/by-riot-id/Player/1115",
            params=None,
            not_found_code="PLAYER_NOT_FOUND",
        )

    assert body == {"puuid": "p"}
    assert seen_header == "RGAPI-fake"


@pytest.mark.asyncio
async def test_riot_client_maps_rate_limit_without_unbounded_sleep() -> None:
    """A long Retry-After must be returned to the caller, not slept indefinitely."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, headers={"Retry-After": "30"}, json={})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
        client = RiotHttpClient(
            api_key="RGAPI-fake",
            client=transport_client,
            retry_max_delay_seconds=2.0,
        )
        with pytest.raises(ApiError) as caught:
            await client.get_json(
                host="americas.api.riotgames.com",
                path="/test",
                params=None,
                not_found_code="PLAYER_NOT_FOUND",
            )

    assert caught.value.status_code == 429
    assert caught.value.code == "RIOT_RATE_LIMITED"
    assert caught.value.params == {"retry_after_seconds": 30}
    assert caught.value.retryable is True


@pytest.mark.asyncio
async def test_riot_client_retries_short_rate_limit_once() -> None:
    """Only a bounded Retry-After permits the single GET retry."""
    requests = 0
    sleeps: list[float] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx2.Response(429, headers={"Retry-After": "1"}, json={})
        return httpx2.Response(200, json={"ok": True})

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
        body = await RiotHttpClient(
            api_key="RGAPI-fake", client=transport_client, sleep=record_sleep
        ).get_json(
            host="americas.api.riotgames.com",
            path="/test",
            params=None,
            not_found_code="PLAYER_NOT_FOUND",
        )

    assert body == {"ok": True}
    assert requests == 2
    assert sleeps == [1]


@pytest.mark.asyncio
async def test_riot_client_maps_invalid_riot_request_without_retry() -> None:
    """A 400 reflects an internal request-contract error, not a transient fault."""
    requests = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        return httpx2.Response(400, json={})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
        with pytest.raises(ApiError) as caught:
            await RiotHttpClient(api_key="RGAPI-fake", client=transport_client).get_json(
                host="americas.api.riotgames.com",
                path="/test",
                params=None,
                not_found_code="PLAYER_NOT_FOUND",
            )

    assert caught.value.status_code == 502
    assert caught.value.code == "RIOT_REQUEST_INVALID"
    assert caught.value.retryable is False
    assert requests == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_riot_client_maps_auth_failures_without_retry(status_code: int) -> None:
    """Authentication failures are terminal and must expose the same safe code."""
    requests = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        return httpx2.Response(status_code, json={})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
        with pytest.raises(ApiError) as caught:
            await RiotHttpClient(api_key="RGAPI-fake", client=transport_client).get_json(
                host="americas.api.riotgames.com",
                path="/test",
                params=None,
                not_found_code="PLAYER_NOT_FOUND",
            )

    assert caught.value.status_code == 503
    assert caught.value.code == "RIOT_AUTH_FAILED"
    assert caught.value.retryable is False
    assert requests == 1


@pytest.mark.asyncio
async def test_riot_client_uses_contextual_not_found_code() -> None:
    """A match lookup must not be reported as a missing player."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, json={})

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
        with pytest.raises(ApiError) as caught:
            await RiotHttpClient(api_key="RGAPI-fake", client=transport_client).get_json(
                host="americas.api.riotgames.com",
                path="/test",
                params=None,
                not_found_code="MATCH_NOT_FOUND",
            )

    assert caught.value.status_code == 404
    assert caught.value.code == "MATCH_NOT_FOUND"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_riot_client_retries_a_server_failure_once() -> None:
    """A transient 5xx should have exactly one bounded retry."""
    requests = 0
    sleeps: list[float] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx2.Response(500, json={})
        return httpx2.Response(200, json={"ok": True})

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
        body = await RiotHttpClient(
            api_key="RGAPI-fake",
            client=transport_client,
            sleep=record_sleep,
            jitter=lambda maximum: 1.5,
        ).get_json(
            host="americas.api.riotgames.com",
            path="/test",
            params=None,
            not_found_code="PLAYER_NOT_FOUND",
        )

    assert body == {"ok": True}
    assert requests == 2
    assert sleeps == [1.5]


@pytest.mark.asyncio
async def test_riot_client_retries_request_timeout_once_then_returns_unavailable() -> None:
    """Transport timeouts are retried once and never expose transport details."""
    requests = 0
    sleeps: list[float] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        raise httpx2.ReadTimeout("upstream timeout", request=request)

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
        with pytest.raises(ApiError) as caught:
            await RiotHttpClient(
                api_key="RGAPI-fake",
                client=transport_client,
                sleep=record_sleep,
                jitter=lambda maximum: 0.5,
            ).get_json(
                host="americas.api.riotgames.com",
                path="/test",
                params=None,
                not_found_code="PLAYER_NOT_FOUND",
            )

    assert caught.value.code == "RIOT_UNAVAILABLE"
    assert caught.value.retryable is True
    assert requests == 2
    assert sleeps == [0.5]


@pytest.mark.asyncio
async def test_riot_client_timeout_budget_cancels_the_first_retry_wait() -> None:
    """The complete retry sequence has one total budget, not two long waits."""
    retry_waits = 0
    blocked = asyncio.Event()

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, json={})

    async def blocking_sleep(seconds: float) -> None:
        nonlocal retry_waits
        retry_waits += 1
        await blocked.wait()

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
        with pytest.raises(ApiError) as caught:
            await RiotHttpClient(
                api_key="RGAPI-fake",
                client=transport_client,
                sleep=blocking_sleep,
                total_timeout_seconds=0.01,
            ).get_json(
                host="americas.api.riotgames.com",
                path="/test",
                params=None,
                not_found_code="PLAYER_NOT_FOUND",
            )

    assert caught.value.code == "RIOT_UNAVAILABLE"
    assert retry_waits == 1


@pytest.mark.asyncio
async def test_riot_client_maps_malformed_json_to_safe_error() -> None:
    """A non-JSON successful response cannot cross the upstream boundary."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"not-json")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
        with pytest.raises(ApiError) as caught:
            await RiotHttpClient(api_key="RGAPI-fake", client=transport_client).get_json(
                host="americas.api.riotgames.com",
                path="/test",
                params=None,
                not_found_code="PLAYER_NOT_FOUND",
            )

    assert caught.value.status_code == 502
    assert caught.value.code == "RIOT_INVALID_RESPONSE"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_riot_client_never_logs_or_returns_an_upstream_secret(caplog) -> None:  # type: ignore[no-untyped-def]
    """Upstream response text and keys must never escape into errors or logs."""
    secret = "RGAPI-response-body-secret"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, text=secret)

    with caplog.at_level(logging.INFO, logger="lol_ai_coach.test"):
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as transport_client:
            with pytest.raises(ApiError) as caught:
                await RiotHttpClient(
                    api_key="RGAPI-injected-secret",
                    client=transport_client,
                    logger=logging.getLogger("lol_ai_coach.test"),
                    sleep=lambda seconds: asyncio.sleep(0),
                ).get_json(
                    host="americas.api.riotgames.com",
                    path="/test",
                    params=None,
                    not_found_code="PLAYER_NOT_FOUND",
                )

    assert secret not in caught.value.message
    assert "RGAPI-injected-secret" not in caplog.text
    assert secret not in caplog.text
