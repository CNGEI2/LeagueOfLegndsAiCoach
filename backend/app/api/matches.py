from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from app.core.dependencies import AppServices, get_services
from app.core.logging import bind_safe_request_context
from app.core.routing import Platform
from app.schemas.domain import Locale
from app.schemas.matches import MatchDetailResponse

router = APIRouter(
    prefix="/api/v1/matches",
    tags=["matches"],
    dependencies=[Depends(bind_safe_request_context)],
)


@router.get("/{match_id}", response_model=MatchDetailResponse)
async def match_detail(
    request: Request,
    match_id: Annotated[str, Path(min_length=1, max_length=64)],
    services: Annotated[AppServices, Depends(get_services)],
    platform: Platform,
    puuid: Annotated[str, Query(min_length=1, max_length=128)],
    locale: Locale = Locale.EN_US,
) -> MatchDetailResponse:
    data = await services.match_service.get_detail(
        platform=platform, match_id=match_id, puuid=puuid, locale=locale
    )
    return MatchDetailResponse(**data.model_dump(), request_id=request.state.request_id)
