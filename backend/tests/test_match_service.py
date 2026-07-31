import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ApiError
from app.core.routing import Platform
from app.schemas.domain import (
    Locale,
    MatchSnapshot,
    PlayerProfile,
    PlayerView,
    StaticAsset,
    StaticDataStatus,
)
from app.services.matches import MatchService
from app.services.parsing.matches import normalize_match
from app.services.riot.dto import MatchDto
from app.services.static_data.resolver import HydratedMatch
from tests.fixtures.riot_payloads import MATCH_PAYLOAD

NOW = datetime(2026, 7, 30, tzinfo=UTC)


class FakePlayerService:
    async def get_by_puuid(self, *, platform: Platform, puuid: str) -> PlayerView:
        profile = PlayerProfile(
            puuid=puuid,
            game_name="Selected",
            tag_line="NA1",
            platform=platform,
            summoner_level=50,
            profile_icon_id=29,
        )
        return PlayerView(
            **profile.model_dump(),
            profile_icon=None,
            profile_static_data_status=StaticDataStatus(
                available=False, version=None, code="STATIC_DATA_UNAVAILABLE"
            ),
        )


class FakeRiotGateway:
    def __init__(self) -> None:
        self.match_ids: tuple[str, ...] = ("NA1_123456789",)
        self.matches: dict[str, MatchDto] = {}
        self.match_id_calls = 0
        self.match_calls: list[str] = []
        self.active_calls = 0
        self.max_active_calls = 0

    async def get_match_ids(self, *, platform: Platform, puuid: str, count: int) -> tuple[str, ...]:
        self.match_id_calls += 1
        return self.match_ids[:count]

    async def get_match(self, *, platform: Platform, match_id: str) -> MatchDto:
        self.match_calls.append(match_id)
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            await asyncio.sleep(0)
            return self.matches[match_id]
        finally:
            self.active_calls -= 1


class FakeRecentRepository:
    def __init__(self) -> None:
        self.cached: tuple[str, ...] | None = None
        self.puts: list[dict[str, object]] = []

    async def get(self, **kwargs: object) -> tuple[str, ...] | None:
        return self.cached

    async def put(self, **kwargs: object) -> None:
        self.puts.append(kwargs)
        self.cached = kwargs["match_ids"]  # type: ignore[assignment]


class FakeMatchRepository:
    def __init__(self) -> None:
        self.cached: dict[str, MatchSnapshot] = {}
        self.cached_fetched_at: dict[str, datetime] = {}
        self.get_calls: list[dict[str, object]] = []
        self.puts: list[tuple[MatchSnapshot, datetime]] = []
        self.cleanup_before: list[datetime] = []

    async def get(self, **kwargs: object) -> MatchSnapshot | None:
        self.get_calls.append(kwargs)
        match_id = str(kwargs["match_id"])
        if self.cached_fetched_at.get(match_id, NOW) < kwargs["fresh_after"]:
            return None
        return self.cached.get(match_id)

    async def put(self, snapshot: MatchSnapshot, *, fetched_at: datetime) -> None:
        self.puts.append((snapshot, fetched_at))
        self.cached[snapshot.match_id] = snapshot
        self.cached_fetched_at[snapshot.match_id] = fetched_at

    async def delete_expired(self, *, before: datetime) -> int:
        self.cleanup_before.append(before)
        return 0


class FakeStaticResolver:
    def __init__(self) -> None:
        self.available = True

    async def hydrate_match(self, snapshot: MatchSnapshot, locale: Locale) -> HydratedMatch:
        from app.schemas.matches import HydratedParticipant

        return HydratedMatch(
            snapshot=snapshot,
            participants=tuple(
                HydratedParticipant(
                    **participant.model_dump(),
                    champion=(
                        StaticAsset(
                            entity_id=participant.champion_id,
                            name="Champion",
                            image_url="https://static.example/champion.png",
                        )
                        if self.available
                        else None
                    ),
                    items=(None,) * len(participant.item_ids),
                )
                for participant in snapshot.participants
            ),
            static_data_status=StaticDataStatus(
                available=self.available,
                version="16.15.1" if self.available else None,
                code=None if self.available else "STATIC_DATA_UNAVAILABLE",
            ),
        )


@dataclass
class MatchServiceDependencies:
    player_service: FakePlayerService = field(default_factory=FakePlayerService)
    riot_gateway: FakeRiotGateway = field(default_factory=FakeRiotGateway)
    recent_repository: FakeRecentRepository = field(default_factory=FakeRecentRepository)
    match_repository: FakeMatchRepository = field(default_factory=FakeMatchRepository)
    static_resolver: FakeStaticResolver = field(default_factory=FakeStaticResolver)

    @staticmethod
    def clock() -> datetime:
        return NOW

    @staticmethod
    def match_dto(match_id: str, *, queue_id: int = 420, participants: int = 10) -> MatchDto:
        payload = json.loads(json.dumps(MATCH_PAYLOAD))
        payload["metadata"]["matchId"] = match_id
        payload["info"]["queueId"] = queue_id
        payload["metadata"]["participants"][0] = "selected-puuid"
        payload["info"]["participants"][0]["puuid"] = "selected-puuid"
        payload["metadata"]["participants"] = payload["metadata"]["participants"][:participants]
        payload["info"]["participants"] = payload["info"]["participants"][:participants]
        return MatchDto.model_validate(payload)


@pytest.fixture
def match_service_dependencies() -> MatchServiceDependencies:
    deps = MatchServiceDependencies()
    deps.riot_gateway.matches["NA1_123456789"] = deps.match_dto("NA1_123456789")
    return deps


def make_service(
    deps: MatchServiceDependencies, *, logger: logging.Logger | None = None
) -> MatchService:
    return MatchService(
        player_service=deps.player_service,
        gateway=deps.riot_gateway,
        recent_repository=deps.recent_repository,
        match_repository=deps.match_repository,
        static_resolver=deps.static_resolver,
        recent_cache_ttl_seconds=120,
        match_retention_days=30,
        max_concurrency=4,
        clock=deps.clock,
        logger=logger,
    )


@pytest.mark.asyncio
async def test_recent_matches_preserve_riot_order_and_mark_supported_queues(
    match_service_dependencies: MatchServiceDependencies,
) -> None:
    deps = match_service_dependencies
    deps.riot_gateway.match_ids = ("NA1_3", "NA1_2", "NA1_1")
    deps.riot_gateway.matches = {
        "NA1_3": deps.match_dto("NA1_3", queue_id=420),
        "NA1_2": deps.match_dto("NA1_2", queue_id=450),
        "NA1_1": deps.match_dto("NA1_1", queue_id=400),
    }

    result = await make_service(deps).list_recent(
        platform=Platform.NA1, puuid="selected-puuid", count=10, locale=Locale.EN_US
    )

    assert [item.match_id for item in result.matches] == ["NA1_3", "NA1_2", "NA1_1"]
    assert [item.analysis_supported for item in result.matches] == [True, False, True]
    assert result.matches[1].unsupported_reason_code == "UNSUPPORTED_QUEUE"


@pytest.mark.asyncio
async def test_recent_id_cache_stores_empty_history_and_uses_it_before_expiry(
    match_service_dependencies: MatchServiceDependencies,
) -> None:
    deps = match_service_dependencies
    deps.riot_gateway.match_ids = ()
    service = make_service(deps)

    first = await service.list_recent(
        platform=Platform.NA1, puuid="selected-puuid", count=10, locale=Locale.EN_US
    )
    second = await service.list_recent(
        platform=Platform.NA1, puuid="selected-puuid", count=10, locale=Locale.EN_US
    )

    assert first.matches == second.matches == ()
    assert deps.riot_gateway.match_id_calls == 1
    assert deps.recent_repository.puts[0]["expires_at"] == NOW + timedelta(seconds=120)


@pytest.mark.asyncio
async def test_recent_match_uses_fresh_completed_match_cache(
    match_service_dependencies: MatchServiceDependencies,
) -> None:
    deps = match_service_dependencies
    snapshot = normalize_match(deps.match_dto("NA1_123456789"), Platform.NA1)
    deps.match_repository.cached[snapshot.match_id] = snapshot

    result = await make_service(deps).list_recent(
        platform=Platform.NA1, puuid="selected-puuid", count=10, locale=Locale.EN_US
    )

    assert result.matches[0].match_id == snapshot.match_id
    assert deps.riot_gateway.match_calls == []
    assert deps.match_repository.get_calls[0]["fresh_after"] == NOW - timedelta(days=30)


@pytest.mark.asyncio
async def test_stale_completed_match_refetches_and_cleans_expired_rows(
    match_service_dependencies: MatchServiceDependencies,
) -> None:
    deps = match_service_dependencies
    stale = normalize_match(deps.match_dto("NA1_123456789"), Platform.NA1)
    deps.match_repository.cached[stale.match_id] = stale
    deps.match_repository.cached_fetched_at[stale.match_id] = NOW - timedelta(days=31)

    await make_service(deps).list_recent(
        platform=Platform.NA1, puuid="selected-puuid", count=10, locale=Locale.EN_US
    )

    assert deps.riot_gateway.match_calls == ["NA1_123456789"]
    assert deps.match_repository.puts[0][1] == NOW
    assert deps.match_repository.cleanup_before == [NOW - timedelta(days=30)]


@pytest.mark.asyncio
async def test_missing_match_fetches_never_exceed_configured_concurrency(
    match_service_dependencies: MatchServiceDependencies,
) -> None:
    deps = match_service_dependencies
    ids = tuple(f"NA1_{index}" for index in range(8))
    deps.riot_gateway.match_ids = ids
    deps.riot_gateway.matches = {match_id: deps.match_dto(match_id) for match_id in ids}

    result = await make_service(deps).list_recent(
        platform=Platform.NA1, puuid="selected-puuid", count=10, locale=Locale.EN_US
    )

    assert [item.match_id for item in result.matches] == list(ids)
    assert deps.riot_gateway.max_active_calls == 4


@pytest.mark.asyncio
async def test_recent_match_fails_when_selected_player_is_absent(
    match_service_dependencies: MatchServiceDependencies,
) -> None:
    deps = match_service_dependencies

    with pytest.raises(ApiError) as raised:
        await make_service(deps).list_recent(
            platform=Platform.NA1, puuid="absent", count=10, locale=Locale.EN_US
        )

    assert raised.value.code == "PLAYER_NOT_IN_MATCH"
    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_nonstandard_mode_remains_visible_but_detail_is_not_supported(
    match_service_dependencies: MatchServiceDependencies,
) -> None:
    deps = match_service_dependencies
    deps.riot_gateway.matches["NA1_123456789"] = deps.match_dto("NA1_123456789", participants=8)

    result = await make_service(deps).list_recent(
        platform=Platform.NA1, puuid="selected-puuid", count=10, locale=Locale.EN_US
    )

    assert len(result.matches) == 1
    assert result.matches[0].detail_supported is False
    assert result.matches[0].detail_unavailable_reason_code == "MATCH_DETAIL_UNSUPPORTED_MODE"


@pytest.mark.asyncio
async def test_match_cache_logs_do_not_include_full_puuid(
    match_service_dependencies: MatchServiceDependencies, caplog: pytest.LogCaptureFixture
) -> None:
    deps = match_service_dependencies
    logger = logging.getLogger("lol_ai_coach.matches.test")
    deps.recent_repository.cached = ()

    with caplog.at_level(logging.INFO, logger=logger.name):
        await make_service(deps, logger=logger).list_recent(
            platform=Platform.NA1, puuid="full-puuid-secret", count=10, locale=Locale.EN_US
        )

    payload = json.loads(caplog.messages[-1])
    assert payload["cache_status"] == "hit"
    assert payload["player_reference_hash"]
    assert "full-puuid-secret" not in caplog.text


@pytest.mark.asyncio
async def test_recent_match_preserves_numeric_data_when_static_hydration_is_degraded(
    match_service_dependencies: MatchServiceDependencies,
) -> None:
    deps = match_service_dependencies
    deps.static_resolver.available = False

    result = await make_service(deps).list_recent(
        platform=Platform.NA1, puuid="selected-puuid", count=10, locale=Locale.ZH_CN
    )

    assert result.matches[0].participant.kills == 1
    assert result.matches[0].participant.champion is None
    assert result.matches[0].static_data_status.code == "STATIC_DATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_match_detail_returns_two_teams_and_replay_binding_metadata(
    match_service_dependencies: MatchServiceDependencies,
) -> None:
    deps = match_service_dependencies

    result = await make_service(deps).get_detail(
        platform=Platform.NA1,
        match_id="NA1_123456789",
        puuid="selected-puuid",
        locale=Locale.ZH_CN,
    )

    assert len(result.blue_team) == 5
    assert len(result.red_team) == 5
    assert result.selected_puuid == "selected-puuid"
    assert result.game_version == "16.15.602.1234"
    assert result.scope_notice_code == "DATA_ONLY_NO_COACHING"


@pytest.mark.asyncio
async def test_match_detail_rejects_absent_player_and_nonstandard_mode(
    match_service_dependencies: MatchServiceDependencies,
) -> None:
    deps = match_service_dependencies
    service = make_service(deps)
    with pytest.raises(ApiError, match="not participate") as absent:
        await service.get_detail(
            platform=Platform.NA1,
            match_id="NA1_123456789",
            puuid="absent",
            locale=Locale.EN_US,
        )
    assert absent.value.code == "PLAYER_NOT_IN_MATCH"

    deps.match_repository.cached.clear()
    deps.riot_gateway.matches["NA1_123456789"] = deps.match_dto("NA1_123456789", participants=8)
    with pytest.raises(ApiError, match="not supported") as unsupported:
        await service.get_detail(
            platform=Platform.NA1,
            match_id="NA1_123456789",
            puuid="selected-puuid",
            locale=Locale.EN_US,
        )
    assert unsupported.value.code == "MATCH_DETAIL_UNSUPPORTED_MODE"
    assert unsupported.value.status_code == 422
