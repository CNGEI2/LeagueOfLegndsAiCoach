from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dependencies import AppServices
from app.main import create_app


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


@pytest.fixture
def fake_services() -> AppServices:
    return AppServices(player_service=FakePlayerService(), closers=())


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
