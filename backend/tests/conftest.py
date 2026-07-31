from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
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
def client(settings: Settings, fake_database: FakeDatabase) -> Generator[TestClient, None, None]:
    with TestClient(create_app(settings=settings, database=fake_database)) as test_client:
        yield test_client


@pytest.fixture
def unavailable_client(settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(
        create_app(settings=settings, database=FakeDatabase(should_fail=True))
    ) as test_client:
        yield test_client
