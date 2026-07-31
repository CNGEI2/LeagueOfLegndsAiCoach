import json
import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ApiError
from app.core.routing import Platform
from app.schemas.domain import PlayerProfile, PlayerView, StaticAsset, StaticDataStatus
from app.services.players import PlayerService
from app.services.riot.dto import AccountDto, SummonerDto

NOW = datetime(2026, 7, 30, tzinfo=UTC)


def profile(
    *, puuid: str = "cached-puuid", game_name: str = "Canonical", tag_line: str = "1115"
) -> PlayerProfile:
    return PlayerProfile(
        puuid=puuid,
        game_name=game_name,
        tag_line=tag_line,
        platform=Platform.NA1,
        summoner_level=50,
        profile_icon_id=29,
    )


class FakePlayerRepository:
    def __init__(self) -> None:
        self.cached_by_riot_id: PlayerProfile | None = None
        self.cached_by_puuid: PlayerProfile | None = None
        self.persisted: list[tuple[PlayerProfile, datetime]] = []
        self.riot_id_queries: list[dict[str, object]] = []
        self.puuid_queries: list[dict[str, object]] = []

    async def get_by_riot_id(self, **kwargs: object) -> PlayerProfile | None:
        self.riot_id_queries.append(kwargs)
        return self.cached_by_riot_id

    async def get_by_puuid(self, **kwargs: object) -> PlayerProfile | None:
        self.puuid_queries.append(kwargs)
        return self.cached_by_puuid

    async def upsert(self, value: PlayerProfile, *, fetched_at: datetime) -> None:
        self.persisted.append((value, fetched_at))


class FakeRiotGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.account = AccountDto(puuid="fresh-puuid", gameName="Canonical Riot", tagLine="1115")
        self.summoner = SummonerDto(
            id="summoner-id",
            accountId="account-id",
            puuid="fresh-puuid",
            profileIconId=30,
            summonerLevel=99,
            revisionDate=1720000000000,
        )
        self.failure: ApiError | None = None

    async def get_account_by_riot_id(
        self, *, platform: Platform, game_name: str, tag_line: str
    ) -> AccountDto:
        self.calls.append(("riot_id", f"{platform}:{game_name}#{tag_line}"))
        if self.failure:
            raise self.failure
        return self.account

    async def get_account_by_puuid(self, *, platform: Platform, puuid: str) -> AccountDto:
        self.calls.append(("puuid", f"{platform}:{puuid}"))
        if self.failure:
            raise self.failure
        return self.account

    async def get_summoner_by_puuid(self, *, platform: Platform, puuid: str) -> SummonerDto:
        self.calls.append(("summoner", f"{platform}:{puuid}"))
        return self.summoner


class FakeStaticResolver:
    async def hydrate_player(self, value: PlayerProfile) -> PlayerView:
        return PlayerView(
            **value.model_dump(),
            profile_icon=StaticAsset(
                entity_id=value.profile_icon_id,
                name="Profile icon",
                image_url="https://static.example/profile.png",
            ),
            profile_static_data_status=StaticDataStatus(
                available=True, version="16.15.1", code=None
            ),
        )


def service(
    repository: FakePlayerRepository,
    gateway: FakeRiotGateway,
    *,
    logger: logging.Logger | None = None,
) -> PlayerService:
    return PlayerService(
        repository=repository,
        gateway=gateway,
        static_resolver=FakeStaticResolver(),
        cache_ttl_seconds=900,
        clock=lambda: NOW,
        logger=logger,
    )


@pytest.mark.asyncio
async def test_resolve_returns_fresh_cache_without_riot_call() -> None:
    """A fresh normalized cache row avoids an unnecessary Riot identity request."""
    repository = FakePlayerRepository()
    repository.cached_by_riot_id = profile()
    gateway = FakeRiotGateway()

    result = await service(repository, gateway).resolve(
        platform=Platform.NA1, game_name=" Canonical ", tag_line=" 1115 "
    )

    assert result.puuid == "cached-puuid"
    assert result.profile_icon is not None
    assert gateway.calls == []
    assert repository.riot_id_queries == [
        {
            "platform": Platform.NA1,
            "game_name_key": "canonical",
            "tag_line_key": "1115",
            "fresh_after": NOW - timedelta(seconds=900),
        }
    ]


@pytest.mark.asyncio
async def test_resolve_persists_canonical_riot_identity_after_cache_miss() -> None:
    """A miss must retain Riot's canonical casing and a numeric tag line in the cache."""
    repository = FakePlayerRepository()
    gateway = FakeRiotGateway()

    result = await service(repository, gateway).resolve(
        platform=Platform.NA1, game_name="entered name", tag_line="1115"
    )

    assert result.game_name == "Canonical Riot"
    assert result.tag_line == "1115"
    assert gateway.calls == [
        ("riot_id", "NA1:entered name#1115"),
        ("summoner", "NA1:fresh-puuid"),
    ]
    assert repository.persisted == [
        (
            PlayerProfile(
                puuid="fresh-puuid",
                game_name="Canonical Riot",
                tag_line="1115",
                platform=Platform.NA1,
                summoner_level=99,
                profile_icon_id=30,
            ),
            NOW,
        )
    ]


@pytest.mark.asyncio
async def test_get_by_puuid_refreshes_through_account_by_puuid_after_cache_miss() -> None:
    """Direct player URLs resolve their canonical account independently of a Riot ID cache key."""
    repository = FakePlayerRepository()
    gateway = FakeRiotGateway()

    result = await service(repository, gateway).get_by_puuid(
        platform=Platform.NA1, puuid="fresh-puuid"
    )

    assert result.puuid == "fresh-puuid"
    assert gateway.calls == [("puuid", "NA1:fresh-puuid"), ("summoner", "NA1:fresh-puuid")]
    assert repository.persisted == [
        (
            PlayerProfile(
                puuid="fresh-puuid",
                game_name="Canonical Riot",
                tag_line="1115",
                platform=Platform.NA1,
                summoner_level=99,
                profile_icon_id=30,
            ),
            NOW,
        )
    ]


@pytest.mark.asyncio
async def test_upstream_failure_does_not_write_a_cache_entry() -> None:
    """Retryable upstream errors must not be persisted as a successful cache refresh."""
    repository = FakePlayerRepository()
    gateway = FakeRiotGateway()
    gateway.failure = ApiError(
        status_code=503,
        code="RIOT_UNAVAILABLE",
        message="Riot is temporarily unavailable.",
        retryable=True,
    )

    with pytest.raises(ApiError, match="temporarily unavailable"):
        await service(repository, gateway).resolve(
            platform=Platform.NA1, game_name="Player", tag_line="1115"
        )

    assert repository.persisted == []


@pytest.mark.asyncio
async def test_cache_logs_hash_player_reference_without_raw_riot_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cache observability must not expose a player's entered Riot ID."""
    repository = FakePlayerRepository()
    repository.cached_by_riot_id = profile()
    gateway = FakeRiotGateway()
    logger = logging.getLogger("lol_ai_coach.players.test")

    with caplog.at_level(logging.INFO, logger=logger.name):
        await service(repository, gateway, logger=logger).resolve(
            platform=Platform.NA1, game_name="Private Player", tag_line="1115"
        )

    payload = json.loads(caplog.messages[-1])
    assert payload["cache_status"] == "hit"
    assert payload["player_reference_hash"]
    assert "Private Player" not in caplog.text
    assert "1115" not in caplog.text
