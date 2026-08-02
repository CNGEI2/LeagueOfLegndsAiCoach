"""Safe local-backend acceptance flow for a configured Riot smoke account."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from typing import Protocol
from urllib.parse import quote

_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,79}$")
_SAFE_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_SAFE_STATUS = frozenset({"resolved", "confirmation_required"})
_SAFE_PLATFORM = re.compile(r"^[A-Z0-9]{2,8}$")


class SmokeResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class SmokeClient(Protocol):
    def get(self, url: str, *, params: Mapping[str, str | int]) -> SmokeResponse: ...

    def post(self, url: str, *, json: Mapping[str, object]) -> SmokeResponse: ...


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


def run_detection_smoke(
    *,
    client: SmokeClient,
    api_base_url: str,
    game_name: str,
    tag_line: str,
    locale: str = "en-US",
) -> None:
    """Detect platforms for a configured Riot ID without printing identifiers."""
    base_url = api_base_url.rstrip("/")
    riot_id = f"{game_name.strip()}#{tag_line.strip()}"
    started = time.perf_counter()
    first = _post_json(
        client,
        f"{base_url}/api/v1/players/detect",
        {"riot_id": riot_id, "locale": locale},
    )
    second = _post_json(
        client,
        f"{base_url}/api/v1/players/detect",
        {"riot_id": riot_id, "locale": locale},
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    first_summary = _detection_summary(first)
    second_summary = _detection_summary(second)
    if first_summary != second_summary:
        raise SmokeFailure("SMOKE_DETECTION_MISMATCH")
    request_id = _safe_request_id(first.get("request_id"))
    request_part = f" request_id={request_id}" if request_id is not None else ""
    print(
        "Phase 2 detection smoke passed: "
        f"status={first_summary['status']} candidates={first_summary['candidates']} "
        f"elapsed_ms={elapsed_ms} repeat=ok{request_part}"
    )


def run_optional_ambiguous_detection_smoke(
    *,
    client: SmokeClient,
    api_base_url: str,
    ambiguous_riot_id: str,
    locale: str = "en-US",
) -> None:
    """Optional multi-platform confirm path. Skips when the Riot ID is unset."""
    trimmed = ambiguous_riot_id.strip()
    if not trimmed:
        print("Phase 2 ambiguous detection smoke skipped: RIOT_SMOKE_AMBIGUOUS_RIOT_ID unset")
        return
    base_url = api_base_url.rstrip("/")
    detected = _post_json(
        client,
        f"{base_url}/api/v1/players/detect",
        {"riot_id": trimmed, "locale": locale},
    )
    if detected.get("status") != "confirmation_required":
        raise SmokeFailure("SMOKE_AMBIGUOUS_EXPECTED")
    candidates = detected.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise SmokeFailure("SMOKE_INVALID_RESPONSE")
    first_candidate = candidates[0]
    if not isinstance(first_candidate, Mapping):
        raise SmokeFailure("SMOKE_INVALID_RESPONSE")
    platform = first_candidate.get("platform")
    if not isinstance(platform, str) or _SAFE_PLATFORM.fullmatch(platform) is None:
        raise SmokeFailure("SMOKE_INVALID_RESPONSE")
    detection_id = _required_string(detected, "detection_id")
    confirmed = _post_json(
        client,
        f"{base_url}/api/v1/players/detect/{quote(detection_id, safe='')}/confirm",
        {"platform": platform, "locale": locale},
    )
    if confirmed.get("status") != "resolved":
        raise SmokeFailure("SMOKE_CONFIRM_FAILED")
    print(f"Phase 2 ambiguous detection smoke passed: candidates={len(candidates)} confirm=ok")


def _detection_summary(payload: Mapping[str, object]) -> dict[str, object]:
    status = payload.get("status")
    if status not in _SAFE_STATUS:
        raise SmokeFailure("SMOKE_INVALID_RESPONSE")
    if status == "resolved":
        player = _required_mapping(payload, "player")
        platform = player.get("platform")
        if not isinstance(platform, str) or _SAFE_PLATFORM.fullmatch(platform) is None:
            raise SmokeFailure("SMOKE_INVALID_RESPONSE")
        return {"status": status, "candidates": 1, "platform": platform}
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise SmokeFailure("SMOKE_INVALID_RESPONSE")
    platforms: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise SmokeFailure("SMOKE_INVALID_RESPONSE")
        platform = candidate.get("platform")
        if not isinstance(platform, str) or _SAFE_PLATFORM.fullmatch(platform) is None:
            raise SmokeFailure("SMOKE_INVALID_RESPONSE")
        platforms.append(platform)
    return {"status": status, "candidates": len(platforms), "platforms": tuple(sorted(platforms))}


def _get_json(client: SmokeClient, url: str, params: Mapping[str, str | int]) -> dict[str, object]:
    try:
        response = client.get(url, params=params)
    except Exception:
        raise SmokeFailure("SMOKE_REQUEST_FAILED") from None
    return _parse_success(response)


def _post_json(client: SmokeClient, url: str, body: Mapping[str, object]) -> dict[str, object]:
    try:
        response = client.post(url, json=body)
    except Exception:
        raise SmokeFailure("SMOKE_REQUEST_FAILED") from None
    return _parse_success(response)


def _parse_success(response: SmokeResponse) -> dict[str, object]:
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


def _safe_request_id(value: object) -> str | None:
    if isinstance(value, str) and _SAFE_REQUEST_ID.fullmatch(value) is not None:
        return value
    return None


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
