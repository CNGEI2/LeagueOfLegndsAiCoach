import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import (
    api_error_handler,
    invalid_platform_selection,
    invalid_riot_id,
    not_found,
    platform_confirmation_expired,
    player_not_found,
    replay_rate_limited,
    riot_platform_detection_unavailable,
)
from app.main import create_app


def test_missing_route_uses_the_error_envelope_and_request_id(client: TestClient) -> None:
    response = client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "The requested resource was not found.",
            "params": {},
            "retryable": False,
            "request_id": response.headers["X-Request-ID"],
        }
    }


def test_cors_exposes_the_request_id_to_browser_clients(client: TestClient) -> None:
    response = client.get("/health/live", headers={"Origin": "http://localhost:3000"})

    assert response.headers["X-Request-ID"]
    exposed = {
        header.strip() for header in response.headers["access-control-expose-headers"].split(",")
    }
    assert exposed == {
        "Accept-Ranges",
        "Content-Length",
        "Content-Range",
        "X-Request-ID",
    }


def test_cors_preflight_includes_a_request_id(client: TestClient) -> None:
    response = client.options(
        "/health/live",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_unhandled_exceptions_keep_request_id_and_cors_headers(
    settings: Settings,
) -> None:
    application = create_app(settings=settings)

    @application.get("/test-only-unhandled-exception")
    async def raise_unhandled_exception() -> None:
        raise RuntimeError("database password: secret")

    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get(
            "/test-only-unhandled-exception",
            headers={"Origin": "http://localhost:3000"},
        )

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "INTERNAL_SERVER_ERROR",
        "message": "An unexpected error occurred.",
        "params": {},
        "retryable": True,
        "request_id": response.headers["X-Request-ID"],
    }
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    exposed = {
        header.strip() for header in response.headers["access-control-expose-headers"].split(",")
    }
    assert "X-Request-ID" in exposed
    assert "secret" not in response.text


def test_platform_detection_error_factories_use_stable_contracts() -> None:
    assert not_found().code == "NOT_FOUND"
    assert not_found().status_code == 404
    assert invalid_riot_id().code == "INVALID_RIOT_ID"
    assert invalid_riot_id().status_code == 422
    assert player_not_found().code == "PLAYER_NOT_FOUND"
    assert player_not_found().retryable is False
    unavailable = riot_platform_detection_unavailable()
    assert unavailable.code == "RIOT_PLATFORM_DETECTION_UNAVAILABLE"
    assert unavailable.status_code == 503
    assert unavailable.retryable is True
    assert platform_confirmation_expired().code == "PLATFORM_CONFIRMATION_EXPIRED"
    assert platform_confirmation_expired().status_code == 409
    assert invalid_platform_selection().code == "INVALID_PLATFORM_SELECTION"
    assert invalid_platform_selection().status_code == 422


def test_replay_rate_limited_sets_retry_after_header_and_params() -> None:
    error = replay_rate_limited(12.4)

    assert error.status_code == 429
    assert error.code == "REPLAY_RATE_LIMITED"
    assert error.retryable is True
    assert error.params["retry_after_seconds"] == 12.4
    assert error.headers["Retry-After"] == "12"


def test_replay_rate_limited_without_retry_after_omits_header() -> None:
    error = replay_rate_limited()

    assert error.params == {}
    assert error.headers == {}


@pytest.mark.asyncio
async def test_validation_errors_use_the_safe_error_envelope() -> None:
    request = Request({"type": "http", "state": {"request_id": "validation-request"}})
    exception = RequestValidationError(
        [
            {
                "type": "missing",
                "loc": ("query", "riot_id"),
                "msg": "Field required",
                "input": None,
            }
        ]
    )

    response = await api_error_handler(request, exception)

    assert response.status_code == 422
    assert response.body == (
        b'{"error":{"code":"VALIDATION_ERROR","message":"Request validation failed.",'
        b'"params":{},"retryable":false,"request_id":"validation-request"}}'
    )


@pytest.mark.asyncio
async def test_unexpected_errors_hide_exception_details() -> None:
    request = Request({"type": "http", "state": {"request_id": "internal-request"}})

    response = await api_error_handler(request, RuntimeError("database password: secret"))

    assert response.status_code == 500
    assert response.body == (
        b'{"error":{"code":"INTERNAL_SERVER_ERROR","message":"An unexpected error occurred.",'
        b'"params":{},"retryable":true,"request_id":"internal-request"}}'
    )
    assert b"secret" not in response.body
