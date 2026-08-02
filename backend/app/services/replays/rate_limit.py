"""In-process gateway rate limiting for the Replay R1 API surface.

Limits are enforced per client IP using rolling windows (creates, ordinary
requests) and a simple concurrency counter (local upload bodies). State is
kept in memory: this is sufficient for a single API process and is expected
to be replaced by a shared backend (e.g. Redis) if the API is ever scaled
horizontally behind a load balancer without sticky sessions.
"""

from __future__ import annotations

import hashlib
import ipaddress
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

from app.core.config import IpNetwork, Settings

_TRUSTED_HEADER = "x-forwarded-for"


class ReplayRateLimitExceeded(Exception):
    """Raised when a caller has exceeded one of the gateway rate limits."""

    def __init__(self, *, retry_after_seconds: float | None = None) -> None:
        super().__init__("replay gateway rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


def hashed_client_ip(ip: str) -> str:
    """Return a stable, non-reversible reference safe for logs/metrics labels."""
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def resolve_client_ip(request: Request, settings: Settings) -> str:
    """Resolve the client IP, only trusting X-Forwarded-For from configured proxies."""
    client = request.client
    direct_ip = client.host if client is not None else "unknown"
    networks: tuple[IpNetwork, ...] = settings.replay_trusted_proxy_networks
    if not networks:
        return direct_ip

    try:
        parsed_direct = ipaddress.ip_address(direct_ip)
    except ValueError:
        return direct_ip

    if not any(parsed_direct in network for network in networks):
        return direct_ip

    forwarded = request.headers.get(_TRUSTED_HEADER)
    if not forwarded:
        return direct_ip

    candidate = forwarded.split(",")[0].strip()
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return direct_ip
    return candidate


class _RollingWindowCounter:
    """Thread-safe fixed-limit counter over a rolling time window per key."""

    def __init__(self, *, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, now: float) -> tuple[bool, float | None]:
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            cutoff = now - self._window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._limit:
                retry_after = bucket[0] + self._window_seconds - now
                return False, max(retry_after, 0.0)
            bucket.append(now)
            return True, None


class _ConcurrencyCounter:
    """Thread-safe counter of concurrently active slots per key."""

    def __init__(self, *, limit: int) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        self._active: dict[str, int] = {}

    def acquire(self, key: str) -> bool:
        with self._lock:
            current = self._active.get(key, 0)
            if current >= self._limit:
                return False
            self._active[key] = current + 1
            return True

    def release(self, key: str) -> None:
        with self._lock:
            current = self._active.get(key, 0)
            if current <= 1:
                self._active.pop(key, None)
            else:
                self._active[key] = current - 1

    def current(self, key: str) -> int:
        with self._lock:
            return self._active.get(key, 0)


@dataclass(frozen=True)
class ReplayRateLimitConfig:
    create_limit: int = 5
    create_window_seconds: float = 3600.0
    request_limit: int = 60
    request_window_seconds: float = 60.0
    upload_concurrency_limit: int = 2

    @classmethod
    def from_settings(cls, settings: Settings) -> ReplayRateLimitConfig:
        return cls(
            create_limit=settings.replay_gateway_create_limit_per_hour,
            request_limit=settings.replay_gateway_request_limit_per_minute,
            upload_concurrency_limit=settings.replay_gateway_upload_concurrency_limit,
        )


class ReplayGatewayRateLimiter:
    """Enforces the Replay R1 gateway rate limits in memory, per client-IP key."""

    def __init__(
        self,
        *,
        config: ReplayRateLimitConfig | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config or ReplayRateLimitConfig()
        self._clock = clock or time.monotonic
        self._create_counter = _RollingWindowCounter(
            limit=self._config.create_limit,
            window_seconds=self._config.create_window_seconds,
        )
        self._request_counter = _RollingWindowCounter(
            limit=self._config.request_limit,
            window_seconds=self._config.request_window_seconds,
        )
        self._upload_concurrency = _ConcurrencyCounter(limit=self._config.upload_concurrency_limit)

    def check_request(self, client_key: str) -> None:
        allowed, retry_after = self._request_counter.hit(client_key, self._clock())
        if not allowed:
            raise ReplayRateLimitExceeded(retry_after_seconds=retry_after)

    def check_create(self, client_key: str) -> None:
        allowed, retry_after = self._create_counter.hit(client_key, self._clock())
        if not allowed:
            raise ReplayRateLimitExceeded(retry_after_seconds=retry_after)

    def acquire_upload_slot(self, client_key: str) -> bool:
        return self._upload_concurrency.acquire(client_key)

    def release_upload_slot(self, client_key: str) -> None:
        self._upload_concurrency.release(client_key)

    def active_upload_slots(self, client_key: str) -> int:
        return self._upload_concurrency.current(client_key)


def build_rate_limiter(settings: Settings) -> ReplayGatewayRateLimiter:
    return ReplayGatewayRateLimiter(config=ReplayRateLimitConfig.from_settings(settings))


__all__ = [
    "ReplayGatewayRateLimiter",
    "ReplayRateLimitConfig",
    "ReplayRateLimitExceeded",
    "build_rate_limiter",
    "hashed_client_ip",
    "resolve_client_ip",
]
