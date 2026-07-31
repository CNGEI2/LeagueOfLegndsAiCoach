from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import AppServices
from app.core.errors import ApiError
from app.core.routing import Platform
from app.main import create_app
from app.schemas.domain import (
    Locale,
    ParticipantSnapshot,
    PlayerProfile,
    PlayerView,
    StaticDataStatus,
)
from app.schemas.matches import (
    HydratedParticipant,
    MatchDetailData,
    RecentMatchesData,
    RecentMatchItem,
)
from tests.conftest import FakeDatabase


def hydrated_participant(
    *, puuid: str = "selected-puuid", team_id: int = 100
) -> HydratedParticipant:
    return HydratedParticipant(
        **ParticipantSnapshot(
            puuid=puuid,
            team_id=team_id,
            champion_id=103,
            role="MIDDLE",
            won=True,
            kills=8,
            deaths=2,
            assists=6,
            cs=201,
            gold_earned=14321,
            damage_to_champions=24567,
            vision_score=18,
            item_ids=(1055,),
        ).model_dump(),
        champion=None,
        items=(None,),
    )


class FakeMatchService:
    def __init__(self) -> None:
        self.error: ApiError | None = None
        self.recent_calls: list[dict[str, object]] = []
        self.detail_calls: list[dict[str, object]] = []
        self.static_degraded = False

    async def list_recent(
        self, *, platform: Platform, puuid: str, count: int, locale: Locale
    ) -> RecentMatchesData:
        self.recent_calls.append(
            {"platform": platform, "puuid": puuid, "count": count, "locale": locale}
        )
        if self.error is not None:
            raise self.error
        profile = PlayerProfile(
            puuid=puuid,
            game_name="Selected",
            tag_line="NA1",
            platform=platform,
            summoner_level=50,
            profile_icon_id=29,
        )
        status = StaticDataStatus(
            available=not self.static_degraded,
            version="16.15.1" if not self.static_degraded else None,
            code=None if not self.static_degraded else "STATIC_DATA_UNAVAILABLE",
        )
        return RecentMatchesData(
            player=PlayerView(
                **profile.model_dump(), profile_icon=None, profile_static_data_status=status
            ),
            matches=tuple(
                RecentMatchItem(
                    match_id=f"NA1_{index}",
                    platform=platform,
                    queue_id=420,
                    started_at=datetime(2026, 7, 30, tzinfo=UTC),
                    duration_seconds=1800,
                    game_version="16.15.602.1234",
                    participant=hydrated_participant(),
                    analysis_supported=True,
                    unsupported_reason_code=None,
                    detail_supported=True,
                    detail_unavailable_reason_code=None,
                    static_data_status=status,
                )
                for index in (3, 2, 1)
            ),
        )

    async def get_detail(
        self, *, platform: Platform, match_id: str, puuid: str, locale: Locale
    ) -> MatchDetailData:
        self.detail_calls.append(
            {"platform": platform, "match_id": match_id, "puuid": puuid, "locale": locale}
        )
        if self.error is not None:
            raise self.error
        return MatchDetailData(
            match_id=match_id,
            platform=platform,
            queue_id=420,
            started_at=datetime(2026, 7, 30, tzinfo=UTC),
            duration_seconds=1800,
            game_version="16.15.602.1234",
            selected_puuid=puuid,
            blue_team=tuple(hydrated_participant(team_id=100) for _ in range(5)),
            red_team=tuple(hydrated_participant(team_id=200) for _ in range(5)),
            static_data_status=StaticDataStatus(available=True, version="16.15.1", code=None),
        )


@pytest.fixture
def match_service() -> FakeMatchService:
    return FakeMatchService()


@pytest.fixture
def match_client(settings, match_service: FakeMatchService) -> Generator[TestClient, None, None]:
    services = AppServices(player_service=object(), match_service=match_service, closers=())
    with TestClient(
        create_app(settings=settings, database=FakeDatabase(), services=services)
    ) as client:
        yield client


def test_recent_match_api_returns_player_and_ordered_matches(match_client: TestClient) -> None:
    response = match_client.get(
        "/api/v1/players/selected-puuid/matches",
        params={"platform": "NA1", "count": 10, "locale": "en-US"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["player"]["puuid"] == "selected-puuid"
    assert [match["match_id"] for match in body["matches"]] == ["NA1_3", "NA1_2", "NA1_1"]
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_match_api_rejects_player_not_in_match_with_unified_envelope(
    match_client: TestClient, match_service: FakeMatchService
) -> None:
    match_service.error = ApiError(
        status_code=404,
        code="PLAYER_NOT_IN_MATCH",
        message="The selected player did not participate in this match.",
        retryable=False,
    )

    response = match_client.get(
        "/api/v1/matches/NA1_123456789",
        params={"platform": "NA1", "puuid": "absent", "locale": "zh-CN"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PLAYER_NOT_IN_MATCH"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize("count", [0, 11])
def test_recent_match_api_validates_count_before_service_call(
    match_client: TestClient, match_service: FakeMatchService, count: int
) -> None:
    response = match_client.get(
        "/api/v1/players/selected-puuid/matches",
        params={"platform": "NA1", "count": count},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert match_service.recent_calls == []


@pytest.mark.parametrize(
    "params",
    [
        {"platform": "EUW1", "count": 10},
        {"platform": "NA1", "count": 10, "locale": "ko-KR"},
    ],
)
def test_recent_match_api_validates_platform_and_locale_before_service_call(
    match_client: TestClient, match_service: FakeMatchService, params: dict[str, object]
) -> None:
    response = match_client.get("/api/v1/players/selected-puuid/matches", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert match_service.recent_calls == []


def test_match_api_returns_safe_riot_rate_limit_error_and_cors(
    match_client: TestClient, match_service: FakeMatchService
) -> None:
    match_service.error = ApiError(
        status_code=429,
        code="RIOT_RATE_LIMITED",
        message="Riot rate limit reached.",
        params={"retry_after_seconds": 2},
        retryable=True,
    )

    response = match_client.get(
        "/api/v1/matches/NA1_123456789",
        params={"platform": "NA1", "puuid": "selected-puuid"},
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RIOT_RATE_LIMITED"
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


@pytest.mark.parametrize(
    ("code", "status"),
    [("MATCH_NOT_FOUND", 404), ("MATCH_DETAIL_UNSUPPORTED_MODE", 422)],
)
def test_match_api_preserves_safe_match_errors(
    match_client: TestClient, match_service: FakeMatchService, code: str, status: int
) -> None:
    match_service.error = ApiError(
        status_code=status,
        code=code,
        message="Safe public message.",
        retryable=False,
    )

    response = match_client.get(
        "/api/v1/matches/NA1_123456789",
        params={"platform": "NA1", "puuid": "selected-puuid"},
    )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "upstream private body" not in response.text


def test_recent_match_api_keeps_degraded_static_data_successful(
    match_client: TestClient, match_service: FakeMatchService
) -> None:
    match_service.static_degraded = True

    response = match_client.get(
        "/api/v1/players/selected-puuid/matches", params={"platform": "NA1"}
    )

    assert response.status_code == 200
    assert response.json()["matches"][0]["participant"]["kills"] == 8
    assert response.json()["matches"][0]["static_data_status"]["code"] == "STATIC_DATA_UNAVAILABLE"
