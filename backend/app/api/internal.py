"""Internal-only endpoints. Not part of the public product API surface.

These are intended to be reached over a private network / sidecar scrape
path only; they are not linked from CORS-exposed headers and carry no
per-replay identifiers, only aggregate counts.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Header, Request
from fastapi.responses import PlainTextResponse

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.metrics import MetricsRegistry
from app.core.metrics import metrics as default_metrics

router = APIRouter(prefix="/internal", tags=["internal"])


def _metrics_not_configured() -> ApiError:
    # Fail closed: with no token configured, the endpoint must behave as if
    # it doesn't exist rather than silently serve metrics to anyone who can
    # reach this process on the network.
    return ApiError(
        status_code=404,
        code="INTERNAL_METRICS_NOT_CONFIGURED",
        message="The requested resource was not found.",
        retryable=False,
    )


def _metrics_unauthorized() -> ApiError:
    return ApiError(
        status_code=401,
        code="INTERNAL_METRICS_UNAUTHORIZED",
        message="A valid bearer token is required to access this resource.",
        retryable=False,
    )


@router.get("/metrics", response_class=PlainTextResponse)
async def get_metrics(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> PlainTextResponse:
    settings = cast(Settings, request.app.state.settings)
    expected_token = settings.internal_metrics_token.get_secret_value()
    if not expected_token:
        raise _metrics_not_configured()

    parts = (authorization or "").split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != expected_token:
        raise _metrics_unauthorized()

    registry = getattr(request.app.state, "replay_metrics", None)
    resolved = cast(MetricsRegistry, registry) if registry is not None else default_metrics
    return PlainTextResponse(
        resolved.render_prometheus_text(),
        media_type="text/plain; version=0.0.4",
    )
