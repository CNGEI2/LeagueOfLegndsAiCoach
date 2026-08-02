"""Internal-only endpoints. Not part of the public product API surface.

These are intended to be reached over a private network / sidecar scrape
path only; they are not linked from CORS-exposed headers and carry no
per-replay identifiers, only aggregate counts.
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.core.metrics import MetricsRegistry
from app.core.metrics import metrics as default_metrics

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/metrics", response_class=PlainTextResponse)
async def get_metrics(request: Request) -> PlainTextResponse:
    registry = getattr(request.app.state, "replay_metrics", None)
    resolved = cast(MetricsRegistry, registry) if registry is not None else default_metrics
    return PlainTextResponse(
        resolved.render_prometheus_text(),
        media_type="text/plain; version=0.0.4",
    )
