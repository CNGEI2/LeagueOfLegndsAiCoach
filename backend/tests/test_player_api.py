from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dependencies import AppServices
from app.core.errors import ApiError
from app.core.routing import Platform
from app.main import create_app
from app.schemas.domain import Locale, PlayerProfile, PlayerView, StaticAsset, StaticDataStatus
from app.services.platform_detection import (
    CandidateView,
    ConfirmationRequiredDetection,
    DisabledPlatformDetectionService,
    ResolvedDetection,
)
from tests.conftest import (
    FakeDatabase,
    FakeMatchService,
    FakePlatformDetectionService,
    FakeReplayService,
)


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
        player_service=player_service,
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=FakePlatformDetectionService(),
        closers=(),
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
        params={"platform": "XYZ1", "game_name": "Player", "tag_line": "1115"},
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
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=FakePlatformDetectionService(),
        closers=(closer,),
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
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=FakePlatformDetectionService(),
        closers=(closer,),
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
        replay_service=FakeReplayService(),
        platform_detection_service=FakePlatformDetectionService(),
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


class ControllablePlatformDetectionService:
    def __init__(self) -> None:
        self.detect_calls: list[dict[str, object]] = []
        self.confirm_calls: list[dict[str, object]] = []
        self.detect_result: object | None = None
        self.confirm_result: object | None = None
        self.detect_error: ApiError | None = None
        self.confirm_error: ApiError | None = None

    async def detect(self, *, riot_id: str, locale: Locale):
        self.detect_calls.append({"riot_id": riot_id, "locale": locale})
        if self.detect_error is not None:
            raise self.detect_error
        assert self.detect_result is not None
        return self.detect_result

    async def confirm(self, *, detection_id: UUID, platform: Platform, locale: Locale):
        self.confirm_calls.append(
            {"detection_id": detection_id, "platform": platform, "locale": locale}
        )
        if self.confirm_error is not None:
            raise self.confirm_error
        assert self.confirm_result is not None
        return self.confirm_result


def _player_view(platform: Platform = Platform.NA1) -> PlayerView:
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
        profile_static_data_status=StaticDataStatus(available=True, version="16.15.1", code=None),
    )


@pytest.fixture
def detection_service() -> ControllablePlatformDetectionService:
    return ControllablePlatformDetectionService()


@pytest.fixture
def detection_client(
    settings: Settings, detection_service: ControllablePlatformDetectionService
) -> Generator[TestClient, None, None]:
    enabled = settings.model_copy(update={"riot_platform_detection_enabled": True})
    services = AppServices(
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=detection_service,
        closers=(),
    )
    with TestClient(
        create_app(settings=enabled, database=FakeDatabase(), services=services)
    ) as test_client:
        yield test_client


def test_detect_player_maps_resolved_result(
    detection_client: TestClient, detection_service: ControllablePlatformDetectionService
) -> None:
    detection_service.detect_result = ResolvedDetection(status="resolved", player=_player_view())

    response = detection_client.post(
        "/api/v1/players/detect",
        json={"riot_id": "Canonical Riot#1115", "locale": "en-US"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["player"]["platform"] == "NA1"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert detection_service.detect_calls == [
        {"riot_id": "Canonical Riot#1115", "locale": Locale.EN_US}
    ]


def test_detect_player_maps_confirmation_required_result(
    detection_client: TestClient, detection_service: ControllablePlatformDetectionService
) -> None:
    detection_id = uuid4()
    expires_at = datetime(2026, 8, 2, 12, 15, tzinfo=UTC)
    detection_service.detect_result = ConfirmationRequiredDetection(
        status="confirmation_required",
        detection_id=detection_id,
        expires_at=expires_at,
        candidates=(
            CandidateView(platform=Platform.EUW1, display_name="Europe West"),
            CandidateView(platform=Platform.NA1, display_name="North America"),
        ),
    )

    response = detection_client.post(
        "/api/v1/players/detect",
        json={"riot_id": "Player#TAG", "locale": "en-US"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "confirmation_required",
        "detection_id": str(detection_id),
        "expires_at": "2026-08-02T12:15:00Z",
        "candidates": [
            {"platform": "EUW1", "display_name": "Europe West"},
            {"platform": "NA1", "display_name": "North America"},
        ],
        "request_id": response.headers["X-Request-ID"],
    }


def test_confirm_player_platform_maps_resolved_result(
    detection_client: TestClient, detection_service: ControllablePlatformDetectionService
) -> None:
    detection_id = uuid4()
    detection_service.confirm_result = ResolvedDetection(
        status="resolved", player=_player_view(Platform.EUW1)
    )

    response = detection_client.post(
        f"/api/v1/players/detect/{detection_id}/confirm",
        json={"platform": "EUW1", "locale": "zh-CN"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    assert response.json()["player"]["platform"] == "EUW1"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert detection_service.confirm_calls == [
        {"detection_id": detection_id, "platform": Platform.EUW1, "locale": Locale.ZH_CN}
    ]


def test_detect_player_maps_invalid_riot_id_error(
    detection_client: TestClient, detection_service: ControllablePlatformDetectionService
) -> None:
    detection_service.detect_error = ApiError(
        status_code=422,
        code="INVALID_RIOT_ID",
        message="Riot ID is invalid.",
        retryable=False,
    )

    response = detection_client.post(
        "/api/v1/players/detect",
        json={"riot_id": "NoSeparator", "locale": "en-US"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_RIOT_ID"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_detect_player_disabled_feature_returns_not_found(settings: Settings) -> None:
    services = AppServices(
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=DisabledPlatformDetectionService(),
        closers=(),
    )
    with TestClient(
        create_app(settings=settings, database=FakeDatabase(), services=services)
    ) as client:
        response = client.post(
            "/api/v1/players/detect",
            json={"riot_id": "Player#TAG", "locale": "en-US"},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_detect_player_temporary_failure_is_retryable(
    detection_client: TestClient, detection_service: ControllablePlatformDetectionService
) -> None:
    detection_service.detect_error = ApiError(
        status_code=503,
        code="RIOT_PLATFORM_DETECTION_UNAVAILABLE",
        message="Riot platform detection is temporarily unavailable.",
        retryable=True,
    )

    response = detection_client.post(
        "/api/v1/players/detect",
        json={"riot_id": "Player#TAG", "locale": "en-US"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RIOT_PLATFORM_DETECTION_UNAVAILABLE"
    assert response.json()["error"]["retryable"] is True


def test_confirm_player_platform_maps_expiry_and_invalid_selection(
    detection_client: TestClient, detection_service: ControllablePlatformDetectionService
) -> None:
    detection_id = uuid4()
    detection_service.confirm_error = ApiError(
        status_code=409,
        code="PLATFORM_CONFIRMATION_EXPIRED",
        message="Platform confirmation has expired.",
        retryable=False,
    )
    expired = detection_client.post(
        f"/api/v1/players/detect/{detection_id}/confirm",
        json={"platform": "NA1", "locale": "en-US"},
    )
    assert expired.status_code == 409
    assert expired.json()["error"]["code"] == "PLATFORM_CONFIRMATION_EXPIRED"

    detection_service.confirm_error = ApiError(
        status_code=422,
        code="INVALID_PLATFORM_SELECTION",
        message="The selected platform is not a candidate.",
        retryable=False,
    )
    invalid = detection_client.post(
        f"/api/v1/players/detect/{detection_id}/confirm",
        json={"platform": "NA1", "locale": "en-US"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_PLATFORM_SELECTION"


@pytest.mark.parametrize("platform", list(Platform))
def test_resolve_player_compatibility_route_accepts_all_typed_platforms(
    player_client: TestClient, platform: Platform
) -> None:
    response = player_client.get(
        "/api/v1/players/resolve",
        params={"platform": platform.value, "game_name": "Player", "tag_line": "TAG"},
    )
    assert response.status_code == 200
    assert response.json()["player"]["platform"] == platform.value


def test_detect_player_logs_omit_raw_riot_id_and_puuid(
    detection_client: TestClient,
    detection_service: ControllablePlatformDetectionService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    detection_service.detect_result = ResolvedDetection(status="resolved", player=_player_view())
    riot_id = "SecretName#SECRET"
    with caplog.at_level("DEBUG"):
        response = detection_client.post(
            "/api/v1/players/detect",
            json={"riot_id": riot_id, "locale": "en-US"},
        )
    assert response.status_code == 200
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert riot_id not in combined
    assert "selected-puuid" not in combined
