from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.api.internal import router as internal_router
from app.api.matches import router as matches_router
from app.api.players import router as players_router
from app.api.replays import router as replays_router
from app.core.config import Settings
from app.core.database import Database, DatabaseProtocol
from app.core.dependencies import AppServices, build_services
from app.core.errors import ApiError, UnhandledExceptionMiddleware, api_error_handler
from app.core.metrics import MetricsRegistry
from app.core.metrics import metrics as default_metrics
from app.core.request_id import RequestIdMiddleware
from app.services.replays.rate_limit import ReplayGatewayRateLimiter, build_rate_limiter
from app.services.replays.storage.base import ReplayStorage
from app.services.replays.storage.factory import build_replay_storage


def create_app(
    settings: Settings | None = None,
    database: DatabaseProtocol | None = None,
    services: AppServices | None = None,
    replay_storage: ReplayStorage | None = None,
    replay_rate_limiter: ReplayGatewayRateLimiter | None = None,
    replay_metrics: MetricsRegistry | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    resolved_database = database or Database(resolved_settings.database_url)
    if services is None:
        if not isinstance(resolved_database, Database):
            raise TypeError("services must be provided when using a non-SQL database")
        resolved_services = build_services(settings=resolved_settings, database=resolved_database)
    else:
        resolved_services = services

    if replay_storage is not None:
        resolved_storage: ReplayStorage | None = replay_storage
    elif resolved_settings.replay_enabled:
        # Build via the factory (not just the local backend) so a
        # REPLAY_STORAGE_BACKEND=s3 deployment doesn't silently leave
        # app.state.replay_storage as None, which would 404 every replay
        # route (see _storage() in app/api/replays.py).
        resolved_storage = build_replay_storage(resolved_settings)
    else:
        resolved_storage = None

    resolved_rate_limiter = replay_rate_limiter or build_rate_limiter(resolved_settings)
    resolved_metrics = replay_metrics or default_metrics

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.database = resolved_database
        application.state.services = resolved_services
        application.state.replay_storage = resolved_storage
        yield
        try:
            await resolved_services.close()
        finally:
            await resolved_database.close()

    application = FastAPI(title="LoL AI Coach API", version="0.1.0", lifespan=lifespan)
    application.state.settings = resolved_settings
    application.state.replay_storage = resolved_storage
    application.state.replay_rate_limiter = resolved_rate_limiter
    application.state.replay_metrics = resolved_metrics
    application.add_exception_handler(ApiError, api_error_handler)
    application.add_exception_handler(RequestValidationError, api_error_handler)
    application.add_exception_handler(StarletteHTTPException, api_error_handler)
    application.add_middleware(UnhandledExceptionMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Accept", "Authorization", "Content-Type", "Range"],
        expose_headers=["Accept-Ranges", "Content-Length", "Content-Range", "X-Request-ID"],
    )
    application.add_middleware(RequestIdMiddleware)
    application.include_router(health_router)
    application.include_router(internal_router)
    application.include_router(players_router)
    application.include_router(matches_router)
    application.include_router(replays_router)
    return application


app = create_app()
