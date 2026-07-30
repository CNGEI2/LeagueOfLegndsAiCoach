from fastapi.testclient import TestClient


def test_liveness_returns_service_identity(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "lol-ai-coach-backend",
    }


def test_readiness_pings_database(client: TestClient, fake_database: object) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert getattr(fake_database, "ping_count") == 1  # noqa: B009


def test_readiness_returns_safe_503_when_database_fails(
    unavailable_client: TestClient,
) -> None:
    response = unavailable_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert set(payload) == {"error"}
    assert payload["error"]["code"] == "SERVICE_NOT_READY"
    assert payload["error"]["params"] == {}
    assert payload["error"]["retryable"] is True
    assert payload["error"]["message"]
    assert payload["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "database unavailable" not in response.text
