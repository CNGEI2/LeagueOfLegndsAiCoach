from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dependencies import AppServices
from app.core.errors import ApiError
from app.core.routing import Platform
from app.main import create_app
from app.schemas.domain import PlayerProfile, PlayerView, StaticAsset, StaticDataStatus
from tests.conftest import FakeDatabase, FakeMatchService


class FakePlayerService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: ApiError | None = None

    async def resolve(self, *, platform: Platform, game_name: str, tag_line: str) -> PlayerView:
        self.calls.append({"platform": platform, "game_name": game_name, "tag_line": tag_line})
        if self.error is not None:
            raise self.error
        return PlayerView(
            **PlayerProfile(
                puuid="selected-puuid",
                game_name="Canonical Riot",
                tag_line="1115",
                platform=platform,
                summoner_level=772,
                profile_icon_id=29,
            ).model_dump(),
            profile_icon=StaticAsset(
                entity_id=29,
                name="Profile icon 29",
                image_url="https://static.example/29.png",
            ),
            profile_static_data_status=StaticDataStatus(
                available=True, version="16.15.1", code=None
            ),
        )

    async def get_by_puuid(self, *, platform: Platform, puuid: str) -> PlayerView:
        raise AssertionError(f"unexpected direct player lookup: {platform}:{puuid}")


class FakeCloser:
    def __init__(self) -> None:
        self.close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1


@pytest.fixture
def player_service() -> FakePlayerService:
    return FakePlayerService()


@pytest.fixture
def player_client(
    settings: Settings, player_service: FakePlayerService
) -> Generator[TestClient, None, None]:
    services = AppServices(
        player_service=player_service, match_service=FakeMatchService(), closers=()
    )
    with TestClient(
        create_app(settings=settings, database=FakeDatabase(), services=services)
    ) as test_client:
        yield test_client


def test_resolve_player_accepts_tag_line_unrelated_to_platform(
    player_client: TestClient,
) -> None:
    response = player_client.get(
        "/api/v1/players/resolve",
        params={"platform": "NA1", "game_name": "PlayerName", "tag_line": "1115"},
    )

    assert response.status_code == 200
    assert response.json()["player"]["tag_line"] == "1115"
    assert response.json()["player"]["platform"] == "NA1"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    ("game_name", "tag_line"),
    [("x" * 33, "1115"), ("Player", "x" * 17), ("   ", "1115"), ("Player", "\t")],
)
def test_resolve_player_rejects_invalid_present_riot_id_before_service_call(
    player_client: TestClient,
    player_service: FakePlayerService,
    game_name: str,
    tag_line: str,
) -> None:
    response = player_client.get(
        "/api/v1/players/resolve",
        params={"platform": "NA1", "game_name": game_name, "tag_line": tag_line},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_RIOT_ID"
    assert player_service.calls == []


def test_resolve_player_trims_unicode_code_point_input_before_service_call(
    player_client: TestClient, player_service: FakePlayerService
) -> None:
    response = player_client.get(
        "/api/v1/players/resolve",
        params={"platform": "NA1", "game_name": "  玩家  ", "tag_line": "  1115\t"},
    )

    assert response.status_code == 200
    assert player_service.calls == [
        {"platform": Platform.NA1, "game_name": "玩家", "tag_line": "1115"}
    ]


def test_resolve_player_uses_global_validation_error_for_missing_query_parameter(
    player_client: TestClient,
) -> None:
    response = player_client.get(
        "/api/v1/players/resolve", params={"platform": "NA1", "game_name": "Player"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_resolve_player_passthroughs_safe_riot_error_and_cors_headers(
    player_client: TestClient, player_service: FakePlayerService
) -> None:
    player_service.error = ApiError(
        status_code=429,
        code="RIOT_RATE_LIMITED",
        message="Riot rate limit reached.",
        retryable=True,
        params={"retry_after_seconds": 2},
    )

    response = player_client.get(
        "/api/v1/players/resolve",
        params={"platform": "NA1", "game_name": "Player", "tag_line": "1115"},
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "RIOT_RATE_LIMITED",
        "message": "Riot rate limit reached.",
        "params": {"retry_after_seconds": 2},
        "retryable": True,
        "request_id": response.headers["X-Request-ID"],
    }
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_resolve_player_rejects_unsupported_platform(player_client: TestClient) -> None:
    response = player_client.get(
        "/api/v1/players/resolve",
        params={"platform": "EUW1", "game_name": "Player", "tag_line": "1115"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_lifespan_closes_services_before_database_exactly_once(settings: Settings) -> None:
    order: list[str] = []

    class OrderedDatabase(FakeDatabase):
        async def close(self) -> None:
            order.append("database")
            await super().close()

    class OrderedCloser(FakeCloser):
        async def aclose(self) -> None:
            order.append("services")
            await super().aclose()

    database = OrderedDatabase()
    closer = OrderedCloser()
    services = AppServices(
        player_service=FakePlayerService(), match_service=FakeMatchService(), closers=(closer,)
    )

    with TestClient(create_app(settings=settings, database=database, services=services)):
        pass

    assert order == ["services", "database"]
    assert closer.close_count == 1
    assert database.close_count == 1


def test_lifespan_closes_database_when_service_shutdown_fails(settings: Settings) -> None:
    """A failed client close must not leave the database pool alive during shutdown."""
    order: list[str] = []

    class OrderedDatabase(FakeDatabase):
        async def close(self) -> None:
            order.append("database")
            await super().close()

    class FailingCloser(FakeCloser):
        async def aclose(self) -> None:
            order.append("services")
            await super().aclose()
            raise RuntimeError("close failed")

    database = OrderedDatabase()
    closer = FailingCloser()
    services = AppServices(
        player_service=FakePlayerService(), match_service=FakeMatchService(), closers=(closer,)
    )

    with (
        pytest.raises(RuntimeError, match="close failed"),
        TestClient(create_app(settings=settings, database=database, services=services)),
    ):
        pass

    assert order == ["services", "database"]
    assert closer.close_count == 1
    assert database.close_count == 1


def test_lifespan_attempts_all_service_closers_after_a_close_failure(settings: Settings) -> None:
    """Every owned HTTP client must be closed even when an earlier client close fails."""
    order: list[str] = []

    class OrderedDatabase(FakeDatabase):
        async def close(self) -> None:
            order.append("database")
            await super().close()

    class FailingCloser(FakeCloser):
        async def aclose(self) -> None:
            order.append("first")
            await super().aclose()
            raise RuntimeError("first close failed")

    class SecondCloser(FakeCloser):
        async def aclose(self) -> None:
            order.append("second")
            await super().aclose()

    database = OrderedDatabase()
    first = FailingCloser()
    second = SecondCloser()
    services = AppServices(
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        closers=(first, second),
    )

    with (
        pytest.raises(RuntimeError, match="first close failed"),
        TestClient(create_app(settings=settings, database=database, services=services)),
    ):
        pass

    assert order == ["first", "second", "database"]
    assert first.close_count == 1
    assert second.close_count == 1
    assert database.close_count == 1
