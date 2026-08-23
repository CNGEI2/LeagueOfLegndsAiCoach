from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import AppServices, get_services
from app.core.logging import bind_safe_request_context
from app.core.metrics import record_analysis_api_request
from app.schemas.analyses import AnalysisCreateRequest, AnalysisResponse
from app.schemas.domain import Locale
from app.services.analyses.domain import DeterministicAnalysisResult

router = APIRouter(
    prefix="/api/v1/analyses",
    tags=["analyses"],
    dependencies=[Depends(bind_safe_request_context)],
)


def to_analysis_response(
    *,
    analysis_id: UUID,
    result: DeterministicAnalysisResult,
    cached: bool,
    locale: Locale,
    request_id: str,
) -> AnalysisResponse:
    return AnalysisResponse(
        analysis_id=analysis_id,
        status=result.status,
        cached=cached,
        locale=locale,
        role=result.role,
        metrics=result.metrics,
        scores=result.scores,
        findings=result.findings,
        goals=result.goals,
        unavailable_reasons=result.unavailable_reasons,
        input_hash=result.input_hash,
        metric_version=result.metric_version,
        score_version=result.score_version,
        rules_version=result.rules_version,
        schema_version=result.schema_version,
        scope_notice_code="DETERMINISTIC_DATA_COACHING_NO_AI",
        request_id=request_id,
    )


@router.post("", response_model=AnalysisResponse)
async def create_analysis(
    request: Request,
    body: AnalysisCreateRequest,
    services: Annotated[AppServices, Depends(get_services)],
) -> AnalysisResponse:
    analysis_id, result, created = await services.analysis_service.create_or_reuse(
        platform=body.platform,
        match_id=body.match_id,
        puuid=body.puuid,
    )
    response = to_analysis_response(
        analysis_id=analysis_id,
        result=result,
        cached=not created,
        locale=body.locale,
        request_id=request.state.request_id,
    )
    registry = getattr(request.app.state, "replay_metrics", None)
    if registry is not None:
        record_analysis_api_request(registry, outcome="ready", error_code="none")
    return response


@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    request: Request,
    analysis_id: UUID,
    services: Annotated[AppServices, Depends(get_services)],
    locale: Locale = Locale.EN_US,
) -> AnalysisResponse:
    result = await services.analysis_service.get(analysis_id=analysis_id)
    response = to_analysis_response(
        analysis_id=analysis_id,
        result=result,
        cached=True,
        locale=locale,
        request_id=request.state.request_id,
    )
    registry = getattr(request.app.state, "replay_metrics", None)
    if registry is not None:
        record_analysis_api_request(registry, outcome="ready", error_code="none")
    return response
