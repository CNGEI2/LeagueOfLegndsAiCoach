from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import AppServices, get_services
from app.core.errors import ApiError
from app.core.logging import bind_safe_request_context
from app.core.routing import Platform
from app.schemas.players import ResolvePlayerResponse

router = APIRouter(
    prefix="/api/v1/players",
    tags=["players"],
    dependencies=[Depends(bind_safe_request_context)],
)


def validate_riot_id(game_name: str, tag_line: str) -> tuple[str, str]:
    normalized_game_name = game_name.strip()
    normalized_tag_line = tag_line.strip()
    if not 1 <= len(normalized_game_name) <= 32 or not 1 <= len(normalized_tag_line) <= 16:
        raise ApiError(
            status_code=422,
            code="INVALID_RIOT_ID",
            message="Riot ID is invalid.",
            retryable=False,
        )
    return normalized_game_name, normalized_tag_line


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
