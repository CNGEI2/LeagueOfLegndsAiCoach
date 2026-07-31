from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.core.config import Settings
from app.core.database import Database, DatabaseProtocol
from app.core.errors import ApiError, UnhandledExceptionMiddleware, api_error_handler
from app.core.request_id import RequestIdMiddleware


def create_app(
    settings: Settings | None = None,
    database: DatabaseProtocol | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    resolved_database = database or Database(resolved_settings.database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.database = resolved_database
        yield
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
    return application


app = create_app()
