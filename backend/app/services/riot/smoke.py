"""Safe local-backend acceptance flow for a configured Riot smoke account."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Protocol
from urllib.parse import quote

_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,79}$")
_SAFE_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")


class SmokeResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class SmokeClient(Protocol):
    def get(self, url: str, *, params: Mapping[str, str | int]) -> SmokeResponse: ...


class SmokeFailure(RuntimeError):
    """A CLI-safe failure that deliberately excludes URL, identifiers, and body text."""

    def __init__(self, code: str, request_id: str | None = None) -> None:
        self.code = code
        self.request_id = request_id
        suffix = f" request_id={request_id}" if request_id is not None else ""
        super().__init__(f"Phase 2 Riot smoke failed: code={code}{suffix}")


def require_smoke_configuration(
    *, game_name: str, tag_line: str, platform: str, riot_configured: bool
) -> None:
    """Reject missing configuration before any local request is made."""
    if not riot_configured or not game_name.strip() or not tag_line.strip() or not platform.strip():
        raise SmokeFailure("SMOKE_CONFIGURATION_REQUIRED")


def run_smoke(
    *,
    client: SmokeClient,
    api_base_url: str,
    game_name: str,
    tag_line: str,
    platform: str,
) -> None:
    """Exercise resolve, localized details, and a repeat recent-match request safely."""
    base_url = api_base_url.rstrip("/")
    resolved = _get_json(
        client,
        f"{base_url}/api/v1/players/resolve",
        {"platform": platform, "game_name": game_name, "tag_line": tag_line},
    )
    player = _required_mapping(resolved, "player")
    puuid = _required_string(player, "puuid")

    matches_url = f"{base_url}/api/v1/players/{quote(puuid, safe='')}/matches"
    recent = _get_json(
        client,
        matches_url,
        {"platform": platform, "count": 10, "locale": "en-US"},
    )
    matches = recent.get("matches")
    if not isinstance(matches, list):
        raise SmokeFailure("SMOKE_INVALID_RESPONSE")
    if not matches:
        raise SmokeFailure("SMOKE_NO_RECENT_MATCHES")

    detail_match = next(
        (
            match
            for match in matches
            if isinstance(match, Mapping) and match.get("detail_supported") is True
        ),
        None,
    )
    if detail_match is None:
        raise SmokeFailure("SMOKE_NO_DETAIL_SUPPORTED_MATCH")
    match_id = _required_string(detail_match, "match_id")
    detail_url = f"{base_url}/api/v1/matches/{quote(match_id, safe='')}"

    for locale in ("en-US", "zh-CN"):
        _get_json(
            client,
            detail_url,
            {"platform": platform, "puuid": puuid, "locale": locale},
        )
    _get_json(
        client,
        matches_url,
        {"platform": platform, "count": 10, "locale": "en-US"},
    )
    print(f"Phase 2 Riot smoke passed: matches={len(matches)} locales=2 repeat=ok")


def _get_json(client: SmokeClient, url: str, params: Mapping[str, str | int]) -> dict[str, object]:
    try:
        response = client.get(url, params=params)
    except Exception:
        raise SmokeFailure("SMOKE_REQUEST_FAILED") from None

    try:
        response.raise_for_status()
    except Exception:
        raise _backend_failure(response) from None

    try:
        payload = response.json()
    except Exception:
        raise SmokeFailure("SMOKE_INVALID_RESPONSE") from None
    if not isinstance(payload, dict):
        raise SmokeFailure("SMOKE_INVALID_RESPONSE")
    return payload


def _backend_failure(response: SmokeResponse) -> SmokeFailure:
    try:
        payload = response.json()
    except Exception:
        return SmokeFailure("SMOKE_REQUEST_FAILED")
    if not isinstance(payload, dict):
        return SmokeFailure("SMOKE_REQUEST_FAILED")
    error = payload.get("error")
    if not isinstance(error, dict):
        return SmokeFailure("SMOKE_REQUEST_FAILED")
    code = error.get("code")
    request_id = error.get("request_id")
    if not isinstance(code, str) or _SAFE_CODE.fullmatch(code) is None:
        return SmokeFailure("SMOKE_REQUEST_FAILED")
    if isinstance(request_id, str) and _SAFE_REQUEST_ID.fullmatch(request_id) is not None:
        return SmokeFailure(code, request_id)
    return SmokeFailure(code)


def _required_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise SmokeFailure("SMOKE_INVALID_RESPONSE")
    return value


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SmokeFailure("SMOKE_INVALID_RESPONSE")
    return value
