import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from unicodedata import normalize

from app.core.logging import log_safe_operation
from app.core.routing import Platform
from app.repositories.players import PlayerRepository
from app.schemas.domain import PlayerProfile, PlayerView
from app.services.parsing.players import normalize_player
from app.services.riot.dto import AccountDto, SummonerDto


class PlayerGateway(Protocol):
    async def get_account_by_riot_id(
        self, *, platform: Platform, game_name: str, tag_line: str
    ) -> AccountDto: ...

    async def get_account_by_puuid(self, *, platform: Platform, puuid: str) -> AccountDto: ...

    async def get_summoner_by_puuid(self, *, platform: Platform, puuid: str) -> SummonerDto: ...


class PlayerStaticResolver(Protocol):
    async def hydrate_player(self, profile: PlayerProfile) -> PlayerView: ...


class PlayerResolver(Protocol):
    async def resolve(self, *, platform: Platform, game_name: str, tag_line: str) -> PlayerView: ...

    async def get_by_puuid(self, *, platform: Platform, puuid: str) -> PlayerView: ...


def lookup_key(value: str) -> str:
    """Normalize user lookup input without changing Riot's display values."""
    return normalize("NFKC", value.strip()).casefold()


class PlayerService:
    def __init__(
        self,
        *,
        repository: PlayerRepository,
        gateway: PlayerGateway,
        static_resolver: PlayerStaticResolver,
        cache_ttl_seconds: int,
        clock: Callable[[], datetime] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._static_resolver = static_resolver
        self._cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._logger = logger or logging.getLogger("lol_ai_coach.players")

    async def resolve(self, *, platform: Platform, game_name: str, tag_line: str) -> PlayerView:
        now = self._clock()
        game_name_key = lookup_key(game_name)
        tag_line_key = lookup_key(tag_line)
        cached = await self._repository.get_by_riot_id(
            platform=platform,
            game_name_key=game_name_key,
            tag_line_key=tag_line_key,
            fresh_after=self._fresh_after(now),
        )
        reference = f"{platform}:{game_name_key}#{tag_line_key}"
        if cached is not None:
            self._log_cache("hit", reference)
            return await self._static_resolver.hydrate_player(cached)

        self._log_cache("miss", reference)
        account = await self._gateway.get_account_by_riot_id(
            platform=platform, game_name=game_name.strip(), tag_line=tag_line.strip()
        )
        return await self._refresh(profile_account=account, platform=platform, now=now)

    async def get_by_puuid(self, *, platform: Platform, puuid: str) -> PlayerView:
        now = self._clock()
        cached = await self._repository.get_by_puuid(
            platform=platform, puuid=puuid, fresh_after=self._fresh_after(now)
        )
        if cached is not None:
            self._log_cache("hit", f"{platform}:{puuid}")
            return await self._static_resolver.hydrate_player(cached)

        self._log_cache("miss", f"{platform}:{puuid}")
        account = await self._gateway.get_account_by_puuid(platform=platform, puuid=puuid)
        return await self._refresh(profile_account=account, platform=platform, now=now)

    async def _refresh(
        self, *, profile_account: AccountDto, platform: Platform, now: datetime
    ) -> PlayerView:
        summoner = await self._gateway.get_summoner_by_puuid(
            platform=platform, puuid=profile_account.puuid
        )
        profile = normalize_player(profile_account, summoner, platform)
        await self._repository.upsert(profile, fetched_at=now)
        return await self._static_resolver.hydrate_player(profile)

    def _fresh_after(self, now: datetime) -> datetime:
        return now - timedelta(seconds=self._cache_ttl_seconds)

    def _log_cache(
        self, cache_status: Literal["hit", "miss", "refresh"], player_reference: str
    ) -> None:
        log_safe_operation(
            self._logger,
            event="player_cache",
            safe_status="success",
            upstream="player-cache",
            latency_ms=0,
            retry_count=0,
            cache_status=cache_status,
            player_reference=player_reference,
        )
