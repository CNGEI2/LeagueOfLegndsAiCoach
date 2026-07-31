import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from app.core.errors import ApiError
from app.core.logging import log_safe_operation
from app.core.routing import Platform
from app.repositories.matches import MatchRepository
from app.repositories.recent_matches import RecentMatchRepository
from app.schemas.domain import Locale, MatchSnapshot
from app.schemas.matches import (
    MatchDetailData,
    RecentMatchesData,
    RecentMatchItem,
)
from app.services.parsing.matches import normalize_match, supports_standard_detail
from app.services.players import PlayerResolver
from app.services.riot.dto import MatchDto
from app.services.static_data.resolver import HydratedMatch

_ANALYSIS_QUEUES = frozenset({400, 420})
_MATCH_ID_CACHE_COUNT = 10


class MatchGateway(Protocol):
    async def get_match_ids(
        self, *, platform: Platform, puuid: str, count: int
    ) -> tuple[str, ...]: ...

    async def get_match(self, *, platform: Platform, match_id: str) -> MatchDto: ...


class MatchStaticResolver(Protocol):
    async def hydrate_match(self, snapshot: MatchSnapshot, locale: Locale) -> HydratedMatch: ...


class MatchResolver(Protocol):
    async def list_recent(
        self, *, platform: Platform, puuid: str, count: int, locale: Locale
    ) -> RecentMatchesData: ...

    async def get_detail(
        self, *, platform: Platform, match_id: str, puuid: str, locale: Locale
    ) -> MatchDetailData: ...


class MatchService:
    def __init__(
        self,
        *,
        player_service: PlayerResolver,
        gateway: MatchGateway,
        recent_repository: RecentMatchRepository,
        match_repository: MatchRepository,
        static_resolver: MatchStaticResolver,
        recent_cache_ttl_seconds: int,
        match_retention_days: int,
        max_concurrency: int,
        clock: Callable[[], datetime] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._player_service = player_service
        self._gateway = gateway
        self._recent_repository = recent_repository
        self._match_repository = match_repository
        self._static_resolver = static_resolver
        self._recent_cache_ttl_seconds = recent_cache_ttl_seconds
        self._match_retention_days = match_retention_days
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._logger = logger or logging.getLogger("lol_ai_coach.matches")

    async def list_recent(
        self, *, platform: Platform, puuid: str, count: int, locale: Locale
    ) -> RecentMatchesData:
        player = await self._player_service.get_by_puuid(platform=platform, puuid=puuid)
        match_ids = await self._recent_match_ids(platform=platform, puuid=puuid)
        snapshots = await self._load_matches(platform, match_ids[:count])
        hydrated = await asyncio.gather(
            *(self._static_resolver.hydrate_match(snapshot, locale) for snapshot in snapshots)
        )
        return RecentMatchesData(
            player=player,
            matches=tuple(
                self._recent_item(snapshot=loaded.snapshot, hydrated=loaded, puuid=puuid)
                for loaded in hydrated
            ),
        )

    async def get_detail(
        self, *, platform: Platform, match_id: str, puuid: str, locale: Locale
    ) -> MatchDetailData:
        snapshot = await self._load_missing_match(platform, match_id)
        if puuid not in {participant.puuid for participant in snapshot.participants}:
            raise _player_not_in_match()
        if not supports_standard_detail(snapshot):
            raise _unsupported_detail_mode()
        hydrated = await self._static_resolver.hydrate_match(snapshot, locale)
        blue_team = tuple(
            participant for participant in hydrated.participants if participant.team_id == 100
        )
        red_team = tuple(
            participant for participant in hydrated.participants if participant.team_id == 200
        )
        return MatchDetailData(
            match_id=snapshot.match_id,
            platform=snapshot.platform,
            queue_id=snapshot.queue_id,
            started_at=snapshot.started_at,
            duration_seconds=snapshot.duration_seconds,
            game_version=snapshot.game_version,
            selected_puuid=puuid,
            blue_team=blue_team,
            red_team=red_team,
            static_data_status=hydrated.static_data_status,
        )

    async def _recent_match_ids(self, *, platform: Platform, puuid: str) -> tuple[str, ...]:
        now = self._clock()
        cached = await self._recent_repository.get(platform=platform, puuid=puuid, now=now)
        if cached is not None:
            self._log_recent_cache("hit", platform, puuid)
            return cached
        self._log_recent_cache("miss", platform, puuid)
        match_ids = await self._gateway.get_match_ids(
            platform=platform, puuid=puuid, count=_MATCH_ID_CACHE_COUNT
        )
        await self._recent_repository.put(
            platform=platform,
            puuid=puuid,
            match_ids=match_ids,
            fetched_at=now,
            expires_at=now + timedelta(seconds=self._recent_cache_ttl_seconds),
        )
        return match_ids

    async def _load_missing_match(self, platform: Platform, match_id: str) -> MatchSnapshot:
        now = self._clock()
        retention_boundary = now - timedelta(days=self._match_retention_days)
        cached = await self._match_repository.get(
            platform=platform,
            match_id=match_id,
            fresh_after=retention_boundary,
        )
        if cached is not None:
            return cached
        async with self._semaphore:
            dto = await self._gateway.get_match(platform=platform, match_id=match_id)
        snapshot = normalize_match(dto, platform)
        await self._match_repository.put(snapshot, fetched_at=now)
        await self._match_repository.delete_expired(before=retention_boundary)
        return snapshot

    async def _load_matches(
        self, platform: Platform, match_ids: tuple[str, ...]
    ) -> tuple[MatchSnapshot, ...]:
        return tuple(
            await asyncio.gather(
                *(self._load_missing_match(platform, match_id) for match_id in match_ids)
            )
        )

    def _recent_item(
        self, *, snapshot: MatchSnapshot, hydrated: HydratedMatch, puuid: str
    ) -> RecentMatchItem:
        participant = next(
            (participant for participant in hydrated.participants if participant.puuid == puuid),
            None,
        )
        if participant is None:
            raise _player_not_in_match()
        analysis_supported = snapshot.queue_id in _ANALYSIS_QUEUES
        detail_supported = supports_standard_detail(snapshot)
        return RecentMatchItem(
            match_id=snapshot.match_id,
            platform=snapshot.platform,
            queue_id=snapshot.queue_id,
            started_at=snapshot.started_at,
            duration_seconds=snapshot.duration_seconds,
            game_version=snapshot.game_version,
            participant=participant,
            analysis_supported=analysis_supported,
            unsupported_reason_code=None if analysis_supported else "UNSUPPORTED_QUEUE",
            detail_supported=detail_supported,
            detail_unavailable_reason_code=(
                None if detail_supported else "MATCH_DETAIL_UNSUPPORTED_MODE"
            ),
            static_data_status=hydrated.static_data_status,
        )

    def _log_recent_cache(
        self, cache_status: Literal["hit", "miss", "refresh"], platform: Platform, puuid: str
    ) -> None:
        log_safe_operation(
            self._logger,
            event="recent_match_cache",
            safe_status="success",
            upstream="recent-match-cache",
            latency_ms=0,
            retry_count=0,
            cache_status=cache_status,
            player_reference=f"{platform}:{puuid}",
        )


def _player_not_in_match() -> ApiError:
    return ApiError(
        status_code=404,
        code="PLAYER_NOT_IN_MATCH",
        message="The selected player did not participate in this match.",
        retryable=False,
    )


def _unsupported_detail_mode() -> ApiError:
    return ApiError(
        status_code=422,
        code="MATCH_DETAIL_UNSUPPORTED_MODE",
        message="Match detail is not supported for this game mode.",
        retryable=False,
    )
