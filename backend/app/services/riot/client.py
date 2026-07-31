import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx2

from app.core.errors import ApiError
from app.core.logging import log_safe_operation
from app.core.routing import ROUTES

STATUS_MAPPING: dict[int, tuple[int, str, bool]] = {
    400: (502, "RIOT_REQUEST_INVALID", False),
    401: (503, "RIOT_AUTH_FAILED", False),
    403: (503, "RIOT_AUTH_FAILED", False),
    429: (429, "RIOT_RATE_LIMITED", True),
}

_MESSAGES = {
    "RIOT_REQUEST_INVALID": "Riot request was invalid.",
    "RIOT_AUTH_FAILED": "Riot authentication failed.",
    "RIOT_RATE_LIMITED": "Riot rate limit reached.",
    "RIOT_UNAVAILABLE": "Riot is temporarily unavailable.",
    "RIOT_INVALID_RESPONSE": "Riot returned an invalid response.",
}
_ERROR_STATUS_CODES = {
    "RIOT_REQUEST_INVALID": (502, False),
    "RIOT_AUTH_FAILED": (503, False),
    "RIOT_RATE_LIMITED": (429, True),
    "RIOT_UNAVAILABLE": (503, True),
    "RIOT_INVALID_RESPONSE": (502, False),
}
_APPROVED_HOSTS = frozenset(
    host for route in ROUTES.values() for host in (route.regional_host, route.platform_host)
)


class RiotHttpClient:
    def __init__(
        self,
        *,
        api_key: str,
        client: httpx2.AsyncClient,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[float], float] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        logger: logging.Logger | None = None,
        connect_timeout_seconds: float = 2.0,
        read_timeout_seconds: float = 5.0,
        total_timeout_seconds: float = 10.0,
        retry_max_delay_seconds: float = 2.0,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._sleep = sleep
        self._jitter = jitter or (lambda maximum: maximum)
        self._monotonic = monotonic
        self._logger = logger or logging.getLogger("lol_ai_coach.riot")
        self._request_timeout = httpx2.Timeout(
            read_timeout_seconds,
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
        )
        self._total_timeout_seconds = total_timeout_seconds
        self._retry_max_delay_seconds = retry_max_delay_seconds

    async def get_json(
        self,
        *,
        host: str,
        path: str,
        params: dict[str, str | int] | None,
        not_found_code: str,
    ) -> object:
        if host not in _APPROVED_HOSTS or not path.startswith("/"):
            raise self._error("RIOT_REQUEST_INVALID")
        started_at = self._monotonic()
        retries = 0
        safe_status = "unavailable"
        try:
            async with asyncio.timeout(self._total_timeout_seconds):
                for attempt in range(2):
                    try:
                        response = await self._client.get(
                            f"https://{host}{path}",
                            params=params,
                            headers={"X-Riot-Token": self._api_key},
                            timeout=self._request_timeout,
                        )
                    except httpx2.RequestError:
                        if attempt == 0:
                            retries = 1
                            await self._sleep(self._bounded_jitter())
                            continue
                        raise self._error("RIOT_UNAVAILABLE") from None

                    if response.status_code == 404:
                        safe_status = "not_found"
                        raise ApiError(
                            status_code=404,
                            code=not_found_code,
                            message="Riot resource was not found.",
                            retryable=False,
                        )
                    if response.status_code == 429:
                        retry_after = self._retry_after(response)
                        if (
                            attempt == 0
                            and retry_after is not None
                            and retry_after <= self._retry_max_delay_seconds
                            and retry_after <= self._remaining_budget(started_at)
                        ):
                            retries = 1
                            await self._sleep(retry_after)
                            continue
                        safe_status = "rate_limited"
                        raise self._error("RIOT_RATE_LIMITED", retry_after_seconds=retry_after)
                    if response.status_code in STATUS_MAPPING:
                        _, code, _ = STATUS_MAPPING[response.status_code]
                        safe_status = code.lower()
                        raise self._error(code)
                    if response.status_code >= 500:
                        if attempt == 0:
                            retries = 1
                            await self._sleep(self._bounded_jitter())
                            continue
                        raise self._error("RIOT_UNAVAILABLE")
                    if response.status_code >= 400:
                        raise self._error("RIOT_UNAVAILABLE")
                    try:
                        safe_status = "success"
                        return response.json()
                    except ValueError:
                        safe_status = "invalid_response"
                        raise self._error("RIOT_INVALID_RESPONSE") from None
                raise self._error("RIOT_UNAVAILABLE")
        except TimeoutError:
            safe_status = "unavailable"
            raise self._error("RIOT_UNAVAILABLE") from None
        except ApiError as error:
            safe_status = safe_status if safe_status != "unavailable" else error.code.lower()
            raise
        finally:
            elapsed_ms = max(0, round((self._monotonic() - started_at) * 1000))
            log_safe_operation(
                self._logger,
                event="riot_request",
                safe_status=safe_status,
                upstream="riot",
                latency_ms=elapsed_ms,
                retry_count=retries,
            )

    def _bounded_jitter(self) -> float:
        return min(
            max(0.0, self._jitter(self._retry_max_delay_seconds)), self._retry_max_delay_seconds
        )

    def _remaining_budget(self, started_at: float) -> float:
        return max(0.0, self._total_timeout_seconds - (self._monotonic() - started_at))

    @staticmethod
    def _retry_after(response: httpx2.Response) -> int | None:
        value = response.headers.get("Retry-After")
        try:
            parsed = int(value) if value is not None else None
        except ValueError:
            return None
        return parsed if parsed is not None and parsed >= 0 else None

    @staticmethod
    def _error(code: str, retry_after_seconds: int | None = None) -> ApiError:
        status_code, retryable = _ERROR_STATUS_CODES[code]
        params: dict[str, Any] = {}
        if code == "RIOT_RATE_LIMITED" and retry_after_seconds is not None:
            params["retry_after_seconds"] = retry_after_seconds
        return ApiError(
            status_code=status_code,
            code=code,
            message=_MESSAGES[code],
            params=params,
            retryable=retryable,
        )
