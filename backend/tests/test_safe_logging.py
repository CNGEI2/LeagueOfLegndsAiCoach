import json
import logging
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.core.logging import bind_safe_request_context, log_safe_operation


def test_structured_log_hashes_player_reference_and_omits_secret(caplog) -> None:  # type: ignore[no-untyped-def]
    """Raw player identifiers in observability data would be a privacy leak."""
    with caplog.at_level(logging.INFO, logger="lol_ai_coach.test"):
        log_safe_operation(
            logging.getLogger("lol_ai_coach.test"),
            event="riot_request",
            request_id="request-1",
            route="/api/v1/players/{puuid}/matches",
            safe_status="success",
            upstream="riot-match-v5",
            latency_ms=12,
            retry_count=1,
            cache_status="miss",
            player_reference="full-puuid-secret",
        )

    payload = json.loads(caplog.messages[-1])
    assert payload["request_id"] == "request-1"
    assert payload["route"] == "/api/v1/players/{puuid}/matches"
    assert payload["player_reference_hash"]
    assert "full-puuid-secret" not in caplog.text
    assert "RGAPI" not in caplog.text


@pytest.mark.asyncio
async def test_request_context_uses_the_route_template_not_path_identifiers(caplog) -> None:  # type: ignore[no-untyped-def]
    """Context binding after routing must retain only the route template."""
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/players/full-puuid-secret/matches",
            "headers": [],
            "route": SimpleNamespace(path="/api/v1/players/{puuid}/matches"),
        }
    )
    request.state.request_id = "request-2"
    dependency = bind_safe_request_context(request)
    await anext(dependency)
    try:
        with caplog.at_level(logging.INFO, logger="lol_ai_coach.test"):
            log_safe_operation(
                logging.getLogger("lol_ai_coach.test"),
                event="riot_request",
                safe_status="success",
                upstream="riot",
                latency_ms=1,
                retry_count=0,
            )
    finally:
        await dependency.aclose()

    payload = json.loads(caplog.messages[-1])
    assert payload["request_id"] == "request-2"
    assert payload["route"] == "/api/v1/players/{puuid}/matches"
    assert "full-puuid-secret" not in caplog.text
