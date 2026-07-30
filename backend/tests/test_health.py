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
    assert response.json() == {
        "detail": {
            "code": "SERVICE_NOT_READY",
            "retryable": True,
        }
    }
