from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dependencies import AppServices
from app.main import create_app

# Register once so top-level integration modules (e.g. replay repository contract
# tests) can use session_factory without double-loading tests.integration.conftest.
pytest_plugins = ["tests.integration.db"]


class FakeDatabase:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.ping_count = 0
        self.close_count = 0

    async def ping(self) -> None:
        self.ping_count += 1
        if self.should_fail:
            raise ConnectionError("database unavailable")

    async def close(self) -> None:
        self.close_count += 1


class FakePlayerService:
    async def resolve(self, **kwargs: object) -> object:
        raise AssertionError(f"player service should not be called by health endpoints: {kwargs}")

    async def get_by_puuid(self, **kwargs: object) -> object:
        raise AssertionError(f"player service should not be called by health endpoints: {kwargs}")


class FakeMatchService:
    async def list_recent(self, **kwargs: object) -> object:
        raise AssertionError(f"match service should not be called by health endpoints: {kwargs}")

    async def get_detail(self, **kwargs: object) -> object:
        raise AssertionError(f"match service should not be called by health endpoints: {kwargs}")


class FakeReplayService:
    async def create(self, *args: object, **kwargs: object) -> object:
        raise AssertionError(f"replay service should not be called unexpectedly: {args} {kwargs}")

    async def authorize(self, *args: object, **kwargs: object) -> object:
        raise AssertionError(f"replay service should not be called unexpectedly: {args} {kwargs}")

    async def mark_local_uploaded(self, *args: object, **kwargs: object) -> object:
        raise AssertionError(f"replay service should not be called unexpectedly: {args} {kwargs}")

    async def complete(self, *args: object, **kwargs: object) -> object:
        raise AssertionError(f"replay service should not be called unexpectedly: {args} {kwargs}")

    async def get_status(self, *args: object, **kwargs: object) -> object:
        raise AssertionError(f"replay service should not be called unexpectedly: {args} {kwargs}")

    async def list_artifacts(self, *args: object, **kwargs: object) -> object:
        raise AssertionError(f"replay service should not be called unexpectedly: {args} {kwargs}")

    async def get_ready_artifact_content(self, *args: object, **kwargs: object) -> object:
        raise AssertionError(f"replay service should not be called unexpectedly: {args} {kwargs}")

    async def retry(self, *args: object, **kwargs: object) -> object:
        raise AssertionError(f"replay service should not be called unexpectedly: {args} {kwargs}")

    async def request_delete(self, *args: object, **kwargs: object) -> object:
        raise AssertionError(f"replay service should not be called unexpectedly: {args} {kwargs}")


class FakePlatformDetectionService:
    async def detect(self, *args: object, **kwargs: object) -> object:
        raise AssertionError(
            f"platform detection service should not be called unexpectedly: {args} {kwargs}"
        )

    async def confirm(self, *args: object, **kwargs: object) -> object:
        raise AssertionError(
            f"platform detection service should not be called unexpectedly: {args} {kwargs}"
        )


@pytest.fixture
def fake_services() -> AppServices:
    return AppServices(
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=FakePlatformDetectionService(),
        closers=(),
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        backend_cors_origins="http://localhost:3000",
        riot_api_key="RGAPI-test",
    )


@pytest.fixture
def fake_database() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def client(
    settings: Settings, fake_database: FakeDatabase, fake_services: AppServices
) -> Generator[TestClient, None, None]:
    with TestClient(
        create_app(settings=settings, database=fake_database, services=fake_services)
    ) as test_client:
        yield test_client


@pytest.fixture
def unavailable_client(
    settings: Settings, fake_services: AppServices
) -> Generator[TestClient, None, None]:
    with TestClient(
        create_app(
            settings=settings,
            database=FakeDatabase(should_fail=True),
            services=fake_services,
        )
    ) as test_client:
        yield test_client
