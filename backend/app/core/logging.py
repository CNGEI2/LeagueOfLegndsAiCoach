import hashlib
import json
import logging
from collections.abc import AsyncIterator
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Literal

from fastapi import Request


@dataclass(frozen=True)
class SafeRequestContext:
    request_id: str
    route: str


_safe_request_context: ContextVar[SafeRequestContext | None] = ContextVar(
    "safe_request_context", default=None
)


def current_safe_request_context() -> SafeRequestContext | None:
    return _safe_request_context.get()


def hashed_player_reference(reference: str) -> str:
    return hashlib.sha256(reference.encode("utf-8")).hexdigest()[:16]


async def bind_safe_request_context(request: Request) -> AsyncIterator[None]:
    route = request.scope.get("route")
    route_template = getattr(route, "path", "")
    context = SafeRequestContext(
        request_id=str(getattr(request.state, "request_id", "")), route=route_template
    )
    token: Token[SafeRequestContext | None] = _safe_request_context.set(context)
    try:
        yield
    finally:
        _safe_request_context.reset(token)


def log_safe_operation(
    logger: logging.Logger,
    *,
    event: str,
    request_id: str | None = None,
    route: str | None = None,
    safe_status: str,
    upstream: str,
    latency_ms: int,
    retry_count: int,
    cache_status: Literal["hit", "miss", "refresh"] | None = None,
    player_reference: str | None = None,
) -> None:
    context = current_safe_request_context()
    record: dict[str, str | int] = {
        "event": event,
        "request_id": request_id
        if request_id is not None
        else (context.request_id if context else ""),
        "route": route if route is not None else (context.route if context else ""),
        "safe_status": safe_status,
        "upstream": upstream,
        "latency_ms": latency_ms,
        "retry_count": retry_count,
    }
    if cache_status is not None:
        record["cache_status"] = cache_status
    if player_reference is not None:
        record["player_reference_hash"] = hashed_player_reference(player_reference)
    logger.info(json.dumps(record, separators=(",", ":"), sort_keys=True))
