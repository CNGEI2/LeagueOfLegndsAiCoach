from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dependencies import AppServices
from app.main import create_app
from tests.conftest import FakeDatabase, FakePlayerService


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


def test_readiness_is_safe_when_riot_key_is_missing(fake_database: FakeDatabase) -> None:
    settings = Settings(
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        backend_cors_origins="http://localhost:3000",
        riot_api_key="",
    )

    services = AppServices(player_service=FakePlayerService(), closers=())
    with TestClient(
        create_app(settings=settings, database=fake_database, services=services)
    ) as test_client:
        response = test_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RIOT_NOT_CONFIGURED"
    assert "RGAPI" not in response.text
    assert fake_database.ping_count == 0
