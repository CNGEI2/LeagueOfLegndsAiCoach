import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from app.core.errors import api_error_handler


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
    assert response.headers["access-control-expose-headers"] == "X-Request-ID"


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
