from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.api.players import router as players_router
from app.core.config import Settings
from app.core.database import Database, DatabaseProtocol
from app.core.dependencies import AppServices, build_services
from app.core.errors import ApiError, UnhandledExceptionMiddleware, api_error_handler
from app.core.request_id import RequestIdMiddleware


def create_app(
    settings: Settings | None = None,
    database: DatabaseProtocol | None = None,
    services: AppServices | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    resolved_database = database or Database(resolved_settings.database_url)
    if services is None:
        if not isinstance(resolved_database, Database):
            raise TypeError("services must be provided when using a non-SQL database")
        resolved_services = build_services(settings=resolved_settings, database=resolved_database)
    else:
        resolved_services = services

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.database = resolved_database
        application.state.services = resolved_services
        yield
        try:
            await resolved_services.close()
        finally:
            await resolved_database.close()

    application = FastAPI(title="LoL AI Coach API", version="0.1.0", lifespan=lifespan)
    application.state.settings = resolved_settings
    application.add_exception_handler(ApiError, api_error_handler)
    application.add_exception_handler(RequestValidationError, api_error_handler)
    application.add_exception_handler(StarletteHTTPException, api_error_handler)
    application.add_middleware(UnhandledExceptionMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
    )
    application.add_middleware(RequestIdMiddleware)
    application.include_router(health_router)
    application.include_router(players_router)
    return application


app = create_app()
