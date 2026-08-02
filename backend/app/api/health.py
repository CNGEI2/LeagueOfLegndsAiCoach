from fastapi import APIRouter, Request, status

from app.core.database import DatabaseProtocol
from app.core.errors import ApiError
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse()


@router.get("/ready", response_model=HealthResponse)
async def ready(request: Request) -> HealthResponse:
    # Readiness must reflect only this process's own ability to serve
    # traffic. It backs the Compose healthcheck for the backend service, so
    # gating it on an optional external dependency (the Riot API key) would
    # wedge the whole stack's startup ordering whenever that key isn't
    # configured yet (e.g. in local/dev environments).
    database: DatabaseProtocol = request.app.state.database
    try:
        await database.ping()
    except Exception as exc:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="SERVICE_NOT_READY",
            message="Service is temporarily unavailable.",
            retryable=True,
        ) from exc
    return HealthResponse()
