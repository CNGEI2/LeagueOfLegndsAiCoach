from dataclasses import dataclass
from typing import Protocol, cast

import httpx2
from fastapi import Request

from app.core.config import Settings
from app.core.database import Database
from app.repositories.matches import SqlMatchRepository
from app.repositories.players import SqlPlayerRepository
from app.repositories.recent_matches import SqlRecentMatchRepository
from app.services.matches import MatchResolver, MatchService
from app.services.players import PlayerResolver, PlayerService
from app.services.riot.client import RiotHttpClient
from app.services.riot.gateway import RiotGateway
from app.services.static_data.client import StaticDataClient
from app.services.static_data.resolver import StaticDataResolver


class AsyncCloser(Protocol):
    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class AppServices:
    player_service: PlayerResolver
    match_service: MatchResolver
    closers: tuple[AsyncCloser, ...]

    async def close(self) -> None:
        first_error: BaseException | None = None
        for closer in self.closers:
            try:
                await closer.aclose()
            except BaseException as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error


def build_services(*, settings: Settings, database: Database) -> AppServices:
    riot_raw_client = httpx2.AsyncClient()
    static_raw_client = httpx2.AsyncClient()
    riot_client = RiotHttpClient(
        api_key=settings.riot_api_key.get_secret_value(),
        client=riot_raw_client,
        connect_timeout_seconds=settings.riot_connect_timeout_seconds,
        read_timeout_seconds=settings.riot_read_timeout_seconds,
        total_timeout_seconds=settings.riot_total_timeout_seconds,
        retry_max_delay_seconds=settings.riot_retry_max_delay_seconds,
    )
    gateway = RiotGateway(riot_client)
    static_resolver = StaticDataResolver(StaticDataClient(static_raw_client))
    player_service = PlayerService(
        repository=SqlPlayerRepository(database.session_factory),
        gateway=gateway,
        static_resolver=static_resolver,
        cache_ttl_seconds=settings.player_cache_ttl_seconds,
    )
    return AppServices(
        player_service=player_service,
        match_service=MatchService(
            player_service=player_service,
            gateway=gateway,
            recent_repository=SqlRecentMatchRepository(database.session_factory),
            match_repository=SqlMatchRepository(database.session_factory),
            static_resolver=static_resolver,
            recent_cache_ttl_seconds=settings.recent_matches_cache_ttl_seconds,
            match_retention_days=settings.match_retention_days,
            max_concurrency=settings.riot_max_concurrency,
        ),
        closers=(riot_raw_client, static_raw_client),
    )


def get_services(request: Request) -> AppServices:
    return cast(AppServices, request.app.state.services)
