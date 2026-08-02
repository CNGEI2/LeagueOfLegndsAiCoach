from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dependencies import AppServices
from app.core.metrics import MetricsRegistry
from app.main import create_app
from app.services.replays.rate_limit import (
    ReplayGatewayRateLimiter,
    ReplayRateLimitConfig,
    ReplayRateLimitExceeded,
    build_rate_limiter,
    hashed_client_ip,
    resolve_client_ip,
)
from app.services.replays.storage.local import LocalReplayStorage
from tests.conftest import FakeDatabase
from tests.test_replay_api import VALID_PAYLOAD, ControllableReplayService

# ---------------------------------------------------------------------------
# Pure unit tests for the in-memory limiter, using a controllable fake clock.
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_create_limit_allows_five_then_blocks_sixth_within_the_hour() -> None:
    clock = FakeClock()
    limiter = ReplayGatewayRateLimiter(
        config=ReplayRateLimitConfig(create_limit=5, create_window_seconds=3600.0),
        clock=clock,
    )

    for _ in range(5):
        limiter.check_create("1.2.3.4")

    with pytest.raises(ReplayRateLimitExceeded) as excinfo:
        limiter.check_create("1.2.3.4")
    assert excinfo.value.retry_after_seconds is not None
    assert excinfo.value.retry_after_seconds > 0


def test_create_limit_is_scoped_per_client_key() -> None:
    clock = FakeClock()
    limiter = ReplayGatewayRateLimiter(
        config=ReplayRateLimitConfig(create_limit=1, create_window_seconds=3600.0),
        clock=clock,
    )

    limiter.check_create("1.2.3.4")
    limiter.check_create("5.6.7.8")  # different key, own budget

    with pytest.raises(ReplayRateLimitExceeded):
        limiter.check_create("1.2.3.4")


def test_create_limit_recovers_after_the_rolling_window_elapses() -> None:
    clock = FakeClock()
    limiter = ReplayGatewayRateLimiter(
        config=ReplayRateLimitConfig(create_limit=1, create_window_seconds=60.0),
        clock=clock,
    )

    limiter.check_create("1.2.3.4")
    with pytest.raises(ReplayRateLimitExceeded):
        limiter.check_create("1.2.3.4")

    clock.advance(60.01)
    limiter.check_create("1.2.3.4")  # does not raise


def test_request_limit_allows_sixty_then_blocks_the_next_within_the_minute() -> None:
    clock = FakeClock()
    limiter = ReplayGatewayRateLimiter(
        config=ReplayRateLimitConfig(request_limit=60, request_window_seconds=60.0),
        clock=clock,
    )

    for _ in range(60):
        limiter.check_request("1.2.3.4")

    with pytest.raises(ReplayRateLimitExceeded):
        limiter.check_request("1.2.3.4")


def test_upload_concurrency_limit_allows_two_then_blocks_a_third() -> None:
    limiter = ReplayGatewayRateLimiter(config=ReplayRateLimitConfig(upload_concurrency_limit=2))

    assert limiter.acquire_upload_slot("1.2.3.4") is True
    assert limiter.acquire_upload_slot("1.2.3.4") is True
    assert limiter.acquire_upload_slot("1.2.3.4") is False

    limiter.release_upload_slot("1.2.3.4")
    assert limiter.acquire_upload_slot("1.2.3.4") is True


def test_upload_concurrency_release_is_scoped_per_client_key() -> None:
    limiter = ReplayGatewayRateLimiter(config=ReplayRateLimitConfig(upload_concurrency_limit=1))

    assert limiter.acquire_upload_slot("1.2.3.4") is True
    assert limiter.acquire_upload_slot("5.6.7.8") is True
    assert limiter.acquire_upload_slot("1.2.3.4") is False

    limiter.release_upload_slot("1.2.3.4")
    assert limiter.active_upload_slots("1.2.3.4") == 0
    assert limiter.active_upload_slots("5.6.7.8") == 1


def test_build_rate_limiter_reads_limits_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        replay_gateway_create_limit_per_hour=2,
        replay_gateway_request_limit_per_minute=3,
        replay_gateway_upload_concurrency_limit=1,
    )
    limiter = build_rate_limiter(settings)

    limiter.check_create("k")
    limiter.check_create("k")
    with pytest.raises(ReplayRateLimitExceeded):
        limiter.check_create("k")

    limiter.check_request("k2")
    limiter.check_request("k2")
    limiter.check_request("k2")
    with pytest.raises(ReplayRateLimitExceeded):
        limiter.check_request("k2")


def test_hashed_client_ip_never_returns_the_raw_ip_and_is_stable() -> None:
    digest = hashed_client_ip("203.0.113.5")
    assert digest != "203.0.113.5"
    assert "203.0.113.5" not in digest
    assert digest == hashed_client_ip("203.0.113.5")


# ---------------------------------------------------------------------------
# Client-IP resolution: only trust X-Forwarded-For from configured proxies.
# ---------------------------------------------------------------------------


def _request(*, client_host: str | None, headers: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "client": (client_host, 12345) if client_host is not None else None,
        "headers": [
            (key.lower().encode(), value.encode()) for key, value in (headers or {}).items()
        ],
        "state": {},
    }
    return Request(scope)


def test_resolve_client_ip_uses_direct_host_when_no_trusted_proxies_configured() -> None:
    settings = Settings(_env_file=None, replay_trusted_proxy_cidrs="")
    request = _request(client_host="203.0.113.9", headers={"X-Forwarded-For": "9.9.9.9"})

    assert resolve_client_ip(request, settings) == "203.0.113.9"


def test_resolve_client_ip_ignores_forwarded_header_from_untrusted_direct_peer() -> None:
    settings = Settings(_env_file=None, replay_trusted_proxy_cidrs="10.0.0.0/8")
    request = _request(client_host="203.0.113.9", headers={"X-Forwarded-For": "9.9.9.9"})

    assert resolve_client_ip(request, settings) == "203.0.113.9"


def test_resolve_client_ip_trusts_forwarded_header_from_configured_proxy_network() -> None:
    settings = Settings(_env_file=None, replay_trusted_proxy_cidrs="10.0.0.0/8,172.16.0.0/12")
    request = _request(client_host="10.1.2.3", headers={"X-Forwarded-For": "9.9.9.9, 10.1.2.3"})

    assert resolve_client_ip(request, settings) == "9.9.9.9"


def test_resolve_client_ip_falls_back_when_forwarded_header_missing() -> None:
    settings = Settings(_env_file=None, replay_trusted_proxy_cidrs="10.0.0.0/8")
    request = _request(client_host="10.1.2.3")

    assert resolve_client_ip(request, settings) == "10.1.2.3"


def test_resolve_client_ip_falls_back_when_no_client_present() -> None:
    settings = Settings(_env_file=None)
    request = _request(client_host=None)

    assert resolve_client_ip(request, settings) == "unknown"


# ---------------------------------------------------------------------------
# API-level enforcement: dependencies actually reject with REPLAY_RATE_LIMITED.
# ---------------------------------------------------------------------------


def _build_client(
    *, tmp_path: Path, rate_limits_enforced: bool, **overrides: object
) -> tuple[TestClient, MetricsRegistry]:
    settings_kwargs: dict[str, object] = {
        "_env_file": None,
        "app_env": "test",
        "database_url": "postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        "backend_cors_origins": "http://localhost:3000",
        "riot_api_key": "RGAPI-test",
        "replay_enabled": True,
        "replay_token_secret": "x" * 32,
        "replay_storage_backend": "local",
        "replay_local_root": tmp_path,
        "replay_max_bytes": 1024,
        "replay_gateway_rate_limits_enforced": rate_limits_enforced,
        "replay_gateway_create_limit_per_hour": 2,
        "replay_gateway_request_limit_per_minute": 3,
        "replay_gateway_upload_concurrency_limit": 1,
    }
    settings_kwargs.update(overrides)
    settings = Settings(**settings_kwargs)  # type: ignore[arg-type]
    services = AppServices(
        player_service=object(),  # type: ignore[arg-type]
        match_service=object(),  # type: ignore[arg-type]
        replay_service=ControllableReplayService(),  # type: ignore[arg-type]
        closers=(),
    )
    registry = MetricsRegistry()
    application = create_app(
        settings=settings,
        database=FakeDatabase(),
        services=services,
        replay_storage=LocalReplayStorage(tmp_path),
        replay_metrics=registry,
    )
    return TestClient(application), registry


@pytest.fixture
def enforced_client(tmp_path: Path) -> Generator[tuple[TestClient, MetricsRegistry], None, None]:
    client, registry = _build_client(tmp_path=tmp_path, rate_limits_enforced=True)
    with client:
        yield client, registry


def test_disabled_rate_limits_never_reject_requests(tmp_path: Path) -> None:
    client, _registry = _build_client(tmp_path=tmp_path, rate_limits_enforced=False)
    with client:
        for _ in range(10):
            response = client.post("/api/v1/replays", json=VALID_PAYLOAD)
            assert response.status_code == 201


def test_create_endpoint_returns_429_after_five_per_hour(
    enforced_client: tuple[TestClient, MetricsRegistry],
) -> None:
    client, registry = enforced_client

    ok1 = client.post("/api/v1/replays", json=VALID_PAYLOAD)
    ok2 = client.post("/api/v1/replays", json=VALID_PAYLOAD)
    limited = client.post("/api/v1/replays", json=VALID_PAYLOAD)

    assert ok1.status_code == 201
    assert ok2.status_code == 201
    assert limited.status_code == 429
    body = limited.json()
    assert body["error"]["code"] == "REPLAY_RATE_LIMITED"
    assert body["error"]["request_id"] == limited.headers["X-Request-ID"]
    assert "Retry-After" in limited.headers
    assert registry.replay_rate_limit_rejections_total.value(limit="creates_per_hour") == 1


def test_ordinary_requests_return_429_after_the_per_minute_limit(
    enforced_client: tuple[TestClient, MetricsRegistry],
) -> None:
    client, registry = enforced_client
    replay_id = ControllableReplayService().create_result.replay_id
    headers = {"Authorization": "Bearer returned-once"}

    responses = [client.get(f"/api/v1/replays/{replay_id}", headers=headers) for _ in range(3)]
    limited = client.get(f"/api/v1/replays/{replay_id}", headers=headers)

    assert all(response.status_code == 200 for response in responses)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "REPLAY_RATE_LIMITED"
    assert registry.replay_rate_limit_rejections_total.value(limit="requests_per_minute") == 1


def test_upload_concurrency_limit_rejects_a_second_concurrent_put(
    enforced_client: tuple[TestClient, MetricsRegistry],
) -> None:
    client, registry = enforced_client
    replay_id = ControllableReplayService().create_result.replay_id
    limiter = client.app.state.replay_rate_limiter  # type: ignore[attr-defined]

    # Simulate an in-flight upload from the same client key by pre-acquiring
    # the single available concurrency slot before issuing the HTTP request.
    probe_request = _request(client_host="testclient")
    client_key = resolve_client_ip(probe_request, client.app.state.settings)  # type: ignore[attr-defined]
    assert limiter.acquire_upload_slot(client_key) is True

    response = client.put(
        f"/api/v1/replays/{replay_id}/content",
        content=b"0123456789",
        headers={"Authorization": "Bearer returned-once", "Content-Length": "10"},
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "REPLAY_RATE_LIMITED"
    assert registry.replay_rate_limit_rejections_total.value(limit="concurrent_uploads") == 1

    limiter.release_upload_slot(client_key)


# ---------------------------------------------------------------------------
# Fail-closed behavior: enforcement must not silently no-op when the limiter
# is missing while enforcement is turned on.
# ---------------------------------------------------------------------------


def test_create_endpoint_fails_closed_with_503_when_limiter_is_missing(
    enforced_client: tuple[TestClient, MetricsRegistry],
) -> None:
    client, _registry = enforced_client
    client.app.state.replay_rate_limiter = None  # type: ignore[attr-defined]

    response = client.post("/api/v1/replays", json=VALID_PAYLOAD)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REPLAY_RATE_LIMITER_UNAVAILABLE"


def test_ordinary_request_fails_closed_with_503_when_limiter_is_missing(
    enforced_client: tuple[TestClient, MetricsRegistry],
) -> None:
    client, _registry = enforced_client
    replay_id = ControllableReplayService().create_result.replay_id
    client.app.state.replay_rate_limiter = None  # type: ignore[attr-defined]

    response = client.get(
        f"/api/v1/replays/{replay_id}",
        headers={"Authorization": "Bearer returned-once"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REPLAY_RATE_LIMITER_UNAVAILABLE"


def test_upload_endpoint_fails_closed_with_503_when_limiter_is_missing(
    enforced_client: tuple[TestClient, MetricsRegistry],
) -> None:
    client, _registry = enforced_client
    replay_id = ControllableReplayService().create_result.replay_id
    client.app.state.replay_rate_limiter = None  # type: ignore[attr-defined]

    response = client.put(
        f"/api/v1/replays/{replay_id}/content",
        content=b"0123456789",
        headers={"Authorization": "Bearer returned-once", "Content-Length": "10"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REPLAY_RATE_LIMITER_UNAVAILABLE"


def test_disabled_rate_limits_do_not_require_a_limiter(tmp_path: Path) -> None:
    """When enforcement is off, a missing limiter must still be a no-op."""
    client, _registry = _build_client(tmp_path=tmp_path, rate_limits_enforced=False)
    with client:
        client.app.state.replay_rate_limiter = None  # type: ignore[attr-defined]
        response = client.post("/api/v1/replays", json=VALID_PAYLOAD)

    assert response.status_code == 201
