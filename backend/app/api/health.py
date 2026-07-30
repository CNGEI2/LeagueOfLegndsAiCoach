from fastapi import APIRouter, HTTPException, Request, status

from app.core.database import DatabaseProtocol
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse()


@router.get("/ready", response_model=HealthResponse)
async def ready(request: Request) -> HealthResponse:
    database: DatabaseProtocol = request.app.state.database
    try:
        await database.ping()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "SERVICE_NOT_READY", "retryable": True},
        ) from exc
    return HealthResponse()
