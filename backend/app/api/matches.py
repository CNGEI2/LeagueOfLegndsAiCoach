from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Request

from app.core.dependencies import AppServices, get_services
from app.core.errors import ApiError, replay_not_found
from app.core.logging import bind_safe_request_context
from app.core.metrics import record_joint_evidence_api_request
from app.core.routing import Platform
from app.schemas.domain import Locale
from app.schemas.evidence import JointEvidenceRequest, JointEvidenceResponse
from app.schemas.matches import MatchDetailResponse
from app.services.replays.security import parse_bearer_token

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


@router.post("/{match_id}/evidence", response_model=JointEvidenceResponse)
async def prepare_match_evidence(
    request: Request,
    match_id: Annotated[str, Path(min_length=1, max_length=64)],
    body: JointEvidenceRequest,
    services: Annotated[AppServices, Depends(get_services)],
    authorization: Annotated[str | None, Header()] = None,
) -> JointEvidenceResponse:
    replay_token = _resolve_evidence_replay_token(
        replay_id=body.replay_id, authorization=authorization
    )
    data = await services.joint_evidence_service.prepare(
        match_id=match_id,
        request=body,
        replay_token=replay_token,
    )
    registry = getattr(request.app.state, "replay_metrics", None)
    if registry is not None:
        record_joint_evidence_api_request(registry, outcome="ready", error_code="none")
    return JointEvidenceResponse(**data.model_dump(), request_id=request.state.request_id)


def _resolve_evidence_replay_token(
    *, replay_id: UUID | None, authorization: str | None
) -> str | None:
    if replay_id is None:
        if authorization is not None:
            raise ApiError(
                status_code=422,
                code="VALIDATION_ERROR",
                message="Request validation failed.",
                retryable=False,
            )
        return None
    token = parse_bearer_token(authorization, required=True)
    if token is None:
        raise replay_not_found()
    return token
