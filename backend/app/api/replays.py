from __future__ import annotations

import contextlib
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Request, Response
from fastapi.responses import StreamingResponse

from app.core.config import Settings
from app.core.dependencies import AppServices, get_services
from app.core.errors import (
    ApiError,
    replay_not_found,
    replay_rate_limited,
    replay_rate_limiter_unavailable,
    replay_too_large,
)
from app.core.logging import bind_safe_request_context
from app.core.metrics import MetricsRegistry
from app.core.metrics import metrics as default_metrics
from app.schemas.replays import (
    ReplayArtifactsResponse,
    ReplayCreateRequest,
    ReplayCreateResponse,
    ReplayStatusResponse,
)
from app.services.replays.domain import ReplayStatus
from app.services.replays.rate_limit import (
    ReplayGatewayRateLimiter,
    ReplayRateLimitExceeded,
    resolve_client_ip,
)
from app.services.replays.storage.base import ReplayObjectTooLarge, ReplayStorage

_MAX_TOKEN_LENGTH = 512
_RANGE_RE = re.compile(r"^bytes=(\d+)-(\d*)$")


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _storage(request: Request) -> ReplayStorage:
    storage = getattr(request.app.state, "replay_storage", None)
    if storage is None:
        raise ApiError(
            status_code=404,
            code="REPLAY_NOT_FOUND",
            message="The requested replay was not found.",
            retryable=False,
        )
    return cast(ReplayStorage, storage)


def _metrics(request: Request) -> MetricsRegistry:
    registry = getattr(request.app.state, "replay_metrics", None)
    return cast(MetricsRegistry, registry) if registry is not None else default_metrics


def _rate_limiter(request: Request) -> ReplayGatewayRateLimiter | None:
    return cast(
        ReplayGatewayRateLimiter | None, getattr(request.app.state, "replay_rate_limiter", None)
    )


def _client_key(request: Request) -> str:
    return resolve_client_ip(request, _settings(request))


async def enforce_gateway_rate_limit(request: Request) -> None:
    """Enforce the 60/minute ordinary-request limit for every replay route."""
    settings = _settings(request)
    if not settings.replay_gateway_rate_limits_enforced:
        return
    limiter = _rate_limiter(request)
    if limiter is None:
        # Enforcement is on but there's nothing to enforce it with: fail
        # closed rather than silently letting every request through
        # unlimited, which is what returning here would do.
        raise replay_rate_limiter_unavailable()
    try:
        limiter.check_request(_client_key(request))
    except ReplayRateLimitExceeded as error:
        _metrics(request).replay_rate_limit_rejections_total.inc(limit="requests_per_minute")
        raise replay_rate_limited(error.retry_after_seconds) from error


async def enforce_create_rate_limit(request: Request) -> None:
    """Enforce the 5/hour replay-create limit, in addition to the request limit."""
    settings = _settings(request)
    if not settings.replay_gateway_rate_limits_enforced:
        return
    limiter = _rate_limiter(request)
    if limiter is None:
        raise replay_rate_limiter_unavailable()
    try:
        limiter.check_create(_client_key(request))
    except ReplayRateLimitExceeded as error:
        _metrics(request).replay_rate_limit_rejections_total.inc(limit="creates_per_hour")
        raise replay_rate_limited(error.retry_after_seconds) from error


async def enforce_upload_concurrency_limit(request: Request) -> AsyncIterator[None]:
    """Enforce the 2-concurrent-local-uploads limit for the duration of the PUT body."""
    settings = _settings(request)
    if not settings.replay_gateway_rate_limits_enforced:
        yield
        return
    limiter = _rate_limiter(request)
    if limiter is None:
        raise replay_rate_limiter_unavailable()
    client_key = _client_key(request)
    if not limiter.acquire_upload_slot(client_key):
        _metrics(request).replay_rate_limit_rejections_total.inc(limit="concurrent_uploads")
        raise replay_rate_limited(None)
    try:
        yield
    finally:
        limiter.release_upload_slot(client_key)


router = APIRouter(
    prefix="/api/v1/replays",
    tags=["replays"],
    dependencies=[
        Depends(bind_safe_request_context),
        Depends(enforce_gateway_rate_limit),
    ],
)


def require_replay_token(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if authorization is None:
        raise replay_not_found()
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise replay_not_found()
    token = parts[1]
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        raise replay_not_found()
    return token


def _parse_byte_range(range_header: str | None, size: int) -> tuple[int, int] | None:
    if range_header is None:
        return None
    if "," in range_header:
        raise ApiError(
            status_code=416,
            code="REPLAY_RANGE_NOT_SATISFIABLE",
            message="The requested byte range is not satisfiable.",
            retryable=False,
            params={"size": size},
        )
    match = _RANGE_RE.fullmatch(range_header.strip())
    if match is None:
        raise ApiError(
            status_code=416,
            code="REPLAY_RANGE_NOT_SATISFIABLE",
            message="The requested byte range is not satisfiable.",
            retryable=False,
            params={"size": size},
        )
    start = int(match.group(1))
    end_raw = match.group(2)
    end = int(end_raw) if end_raw != "" else size - 1
    if size <= 0 or start > end or start >= size or end >= size:
        raise ApiError(
            status_code=416,
            code="REPLAY_RANGE_NOT_SATISFIABLE",
            message="The requested byte range is not satisfiable.",
            retryable=False,
            params={"size": size},
        )
    return start, end


@router.post(
    "",
    response_model=ReplayCreateResponse,
    status_code=201,
    dependencies=[Depends(enforce_create_rate_limit)],
)
async def create_replay(
    request: Request,
    body: ReplayCreateRequest,
    services: Annotated[AppServices, Depends(get_services)],
) -> ReplayCreateResponse:
    data = await services.replay_service.create(body)
    return ReplayCreateResponse(**data.model_dump(), request_id=request.state.request_id)


@router.put(
    "/{replay_id}/content",
    status_code=204,
    response_class=Response,
    dependencies=[Depends(enforce_upload_concurrency_limit)],
)
async def upload_replay_content(
    request: Request,
    replay_id: Annotated[UUID, Path()],
    services: Annotated[AppServices, Depends(get_services)],
    token: Annotated[str, Depends(require_replay_token)],
) -> Response:
    settings = _settings(request)
    if settings.replay_storage_backend != "local":
        raise replay_not_found()

    row = await services.replay_service.authorize(replay_id, token)
    if ReplayStatus(row.status) != ReplayStatus.CREATED or not row.source_object_key:
        raise replay_not_found()
    if row.upload_expires_at <= datetime.now(UTC):
        raise ApiError(
            status_code=410,
            code="REPLAY_UPLOAD_EXPIRED",
            message="The replay upload window has expired.",
            retryable=False,
        )

    max_bytes = min(settings.replay_max_bytes, row.declared_size_bytes)
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise ApiError(
                status_code=422,
                code="REPLAY_UPLOAD_INVALID",
                message="The replay upload declaration is invalid.",
                retryable=False,
            ) from error
        if declared_length > max_bytes:
            raise replay_too_large()

    storage = _storage(request)
    try:
        stored = await storage.write_stream(
            row.source_object_key,
            request.stream(),
            max_bytes=max_bytes,
        )
    except ReplayObjectTooLarge as error:
        raise replay_too_large() from error

    try:
        await services.replay_service.mark_local_uploaded(
            replay_id,
            token,
            actual_size_bytes=stored.size_bytes,
        )
    except Exception:
        # The object was already written to its final key by write_stream
        # above; if the DB transition fails afterward, it must not linger as
        # an orphan, so clean it up before propagating the original error.
        with contextlib.suppress(Exception):
            await storage.delete(row.source_object_key)
        raise
    return Response(status_code=204)


@router.post("/{replay_id}/complete", response_model=ReplayStatusResponse)
async def complete_replay(
    request: Request,
    replay_id: Annotated[UUID, Path()],
    services: Annotated[AppServices, Depends(get_services)],
    token: Annotated[str, Depends(require_replay_token)],
) -> ReplayStatusResponse:
    data = await services.replay_service.complete(replay_id, token)
    return ReplayStatusResponse(**data.model_dump(), request_id=request.state.request_id)


@router.get("/{replay_id}", response_model=ReplayStatusResponse)
async def get_replay_status(
    request: Request,
    replay_id: Annotated[UUID, Path()],
    services: Annotated[AppServices, Depends(get_services)],
    token: Annotated[str, Depends(require_replay_token)],
) -> ReplayStatusResponse:
    data = await services.replay_service.get_status(replay_id, token)
    return ReplayStatusResponse(**data.model_dump(), request_id=request.state.request_id)


@router.get("/{replay_id}/artifacts", response_model=ReplayArtifactsResponse)
async def list_replay_artifacts(
    request: Request,
    replay_id: Annotated[UUID, Path()],
    services: Annotated[AppServices, Depends(get_services)],
    token: Annotated[str, Depends(require_replay_token)],
) -> ReplayArtifactsResponse:
    artifacts = await services.replay_service.list_artifacts(replay_id, token)
    return ReplayArtifactsResponse(
        artifacts=tuple(artifacts),
        request_id=request.state.request_id,
    )


@router.get("/{replay_id}/artifacts/{artifact_id}/content")
async def get_replay_artifact_content(
    request: Request,
    replay_id: Annotated[UUID, Path()],
    artifact_id: Annotated[UUID, Path()],
    services: Annotated[AppServices, Depends(get_services)],
    token: Annotated[str, Depends(require_replay_token)],
) -> StreamingResponse:
    content = await services.replay_service.get_ready_artifact_content(
        replay_id, artifact_id, token
    )
    size = content.size_bytes
    byte_range = _parse_byte_range(request.headers.get("range"), size)
    storage = _storage(request)

    if byte_range is None:
        start, end = 0, size - 1
        status_code = 200
        content_range = None
    else:
        start, end = byte_range
        status_code = 206
        content_range = f"bytes {start}-{end}/{size}"

    async def body() -> AsyncIterator[bytes]:
        async for chunk in storage.iter_range(content.object_key, start, end):
            yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Disposition": f'inline; filename="{content.artifact_id}"',
    }
    if content_range is not None:
        headers["Content-Range"] = content_range

    return StreamingResponse(
        body(),
        status_code=status_code,
        media_type=content.media_type,
        headers=headers,
    )


@router.post("/{replay_id}/retry", response_model=ReplayStatusResponse)
async def retry_replay(
    request: Request,
    replay_id: Annotated[UUID, Path()],
    services: Annotated[AppServices, Depends(get_services)],
    token: Annotated[str, Depends(require_replay_token)],
) -> ReplayStatusResponse:
    data = await services.replay_service.retry(replay_id, token)
    return ReplayStatusResponse(**data.model_dump(), request_id=request.state.request_id)


@router.delete("/{replay_id}", response_model=ReplayStatusResponse)
async def delete_replay(
    request: Request,
    replay_id: Annotated[UUID, Path()],
    services: Annotated[AppServices, Depends(get_services)],
    token: Annotated[str, Depends(require_replay_token)],
) -> ReplayStatusResponse:
    data = await services.replay_service.request_delete(replay_id, token)
    return ReplayStatusResponse(**data.model_dump(), request_id=request.state.request_id)
