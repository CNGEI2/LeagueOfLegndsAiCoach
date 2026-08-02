from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request

from app.core.dependencies import AppServices, get_services
from app.core.errors import invalid_riot_id
from app.core.logging import bind_safe_request_context
from app.core.routing import Platform
from app.schemas.domain import Locale
from app.schemas.matches import RecentMatchesResponse
from app.schemas.platform_detection import (
    ConfirmationRequiredResponse,
    ConfirmPlatformRequest,
    DetectPlayerRequest,
    DetectPlayerResponse,
    PlatformCandidate,
    ResolvedDetectionResponse,
)
from app.schemas.players import ResolvePlayerResponse
from app.services.platform_detection import (
    ConfirmationRequiredDetection,
    DetectionResult,
    ResolvedDetection,
)

router = APIRouter(
    prefix="/api/v1/players",
    tags=["players"],
    dependencies=[Depends(bind_safe_request_context)],
)


def validate_riot_id(game_name: str, tag_line: str) -> tuple[str, str]:
    normalized_game_name = game_name.strip()
    normalized_tag_line = tag_line.strip()
    if not 1 <= len(normalized_game_name) <= 32 or not 1 <= len(normalized_tag_line) <= 16:
        raise invalid_riot_id()
    return normalized_game_name, normalized_tag_line


def _detection_response(result: DetectionResult, *, request_id: str) -> DetectPlayerResponse:
    if isinstance(result, ResolvedDetection):
        return ResolvedDetectionResponse(
            status="resolved",
            player=result.player,
            request_id=request_id,
        )
    if isinstance(result, ConfirmationRequiredDetection):
        return ConfirmationRequiredResponse(
            status="confirmation_required",
            detection_id=result.detection_id,
            expires_at=result.expires_at,
            candidates=tuple(
                PlatformCandidate(platform=candidate.platform, display_name=candidate.display_name)
                for candidate in result.candidates
            ),
            request_id=request_id,
        )
    raise TypeError(f"unsupported detection result: {type(result)!r}")


@router.post("/detect", response_model=DetectPlayerResponse)
async def detect_player(
    request: Request,
    body: DetectPlayerRequest,
    services: Annotated[AppServices, Depends(get_services)],
) -> DetectPlayerResponse:
    result = await services.platform_detection_service.detect(
        riot_id=body.riot_id,
        locale=body.locale,
    )
    return _detection_response(result, request_id=request.state.request_id)


@router.post("/detect/{detection_id}/confirm", response_model=DetectPlayerResponse)
async def confirm_player_platform(
    request: Request,
    detection_id: UUID,
    body: ConfirmPlatformRequest,
    services: Annotated[AppServices, Depends(get_services)],
) -> DetectPlayerResponse:
    result = await services.platform_detection_service.confirm(
        detection_id=detection_id,
        platform=body.platform,
        locale=body.locale,
    )
    return _detection_response(result, request_id=request.state.request_id)


@router.get("/resolve", response_model=ResolvePlayerResponse)
async def resolve_player(
    request: Request,
    platform: Platform,
    game_name: str,
    tag_line: str,
    services: Annotated[AppServices, Depends(get_services)],
) -> ResolvePlayerResponse:
    normalized_game_name, normalized_tag_line = validate_riot_id(game_name, tag_line)
    player = await services.player_service.resolve(
        platform=platform,
        game_name=normalized_game_name,
        tag_line=normalized_tag_line,
    )
    return ResolvePlayerResponse(player=player, request_id=request.state.request_id)


@router.get("/{puuid}/matches", response_model=RecentMatchesResponse)
async def recent_matches(
    request: Request,
    puuid: Annotated[str, Path(min_length=1, max_length=128)],
    services: Annotated[AppServices, Depends(get_services)],
    platform: Platform,
    count: Annotated[int, Query(ge=1, le=10)] = 10,
    locale: Locale = Locale.EN_US,
) -> RecentMatchesResponse:
    data = await services.match_service.list_recent(
        platform=platform, puuid=puuid, count=count, locale=locale
    )
    return RecentMatchesResponse(**data.model_dump(), request_id=request.state.request_id)
