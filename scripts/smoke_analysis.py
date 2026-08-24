"""Run deterministic-analysis acceptance without exposing configured values or payloads."""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from typing import Protocol
from urllib.parse import quote

import httpx2
from app.core.config import Settings

_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,79}$")
_SAFE_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_SAFE_INPUT_HASH = re.compile(r"^[a-f0-9]{64}$")
_DIMENSIONS = ("economy", "combat", "survivability", "team_objectives", "vision")
_RESULT_FIELDS = (
    "analysis_id",
    "status",
    "role",
    "metrics",
    "scores",
    "findings",
    "goals",
    "unavailable_reasons",
    "input_hash",
    "metric_version",
    "score_version",
    "rules_version",
    "schema_version",
    "scope_notice_code",
)


class SmokeResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class SmokeClient(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: Mapping[str, object] | None = None,
    ) -> SmokeResponse: ...


class SmokeFailure(RuntimeError):
    """A CLI-safe failure whose rendered form is only an allowlisted code."""

    def __init__(self, code: str) -> None:
        if _SAFE_CODE.fullmatch(code) is None:
            raise ValueError(
                "smoke failure code must use the stable uppercase allowlist"
            )
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code


def require_smoke_configuration(
    *,
    game_name: str,
    tag_line: str,
    platform: str,
    riot_configured: bool,
    analysis_enabled: bool,
) -> None:
    if (
        not riot_configured
        or not analysis_enabled
        or not game_name.strip()
        or not tag_line.strip()
        or not platform.strip()
    ):
        raise SmokeFailure("ANALYSIS_SMOKE_CONFIGURATION_REQUIRED")


def run_smoke(
    *,
    client: SmokeClient,
    api_base_url: str,
    game_name: str,
    tag_line: str,
    platform: str,
) -> None:
    try:
        _run_smoke(
            client=client,
            api_base_url=api_base_url,
            game_name=game_name,
            tag_line=tag_line,
            platform=platform,
        )
    except SmokeFailure:
        raise
    except Exception:  # noqa: BLE001 - the CLI boundary must redact all unexpected details.
        raise SmokeFailure("ANALYSIS_SMOKE_REQUEST_FAILED") from None


def _run_smoke(
    *,
    client: SmokeClient,
    api_base_url: str,
    game_name: str,
    tag_line: str,
    platform: str,
) -> None:
    base_url = api_base_url.rstrip("/")
    resolved = _request_mapping(
        client,
        "GET",
        f"{base_url}/api/v1/players/resolve",
        params={"platform": platform, "game_name": game_name, "tag_line": tag_line},
    )
    player = _required_mapping(resolved, "player")
    puuid = _required_string(player, "puuid")

    matches = _request_mapping(
        client,
        "GET",
        f"{base_url}/api/v1/players/{quote(puuid, safe='')}/matches",
        params={"platform": platform, "count": 10, "locale": "en-US"},
    ).get("matches")
    if not isinstance(matches, list) or not matches:
        raise SmokeFailure("ANALYSIS_SMOKE_NO_RECENT_MATCHES")
    selected = next(
        (
            item
            for item in matches
            if isinstance(item, Mapping)
            and item.get("analysis_supported") is True
            and item.get("detail_supported") is True
        ),
        None,
    )
    if selected is None:
        raise SmokeFailure("ANALYSIS_SMOKE_NO_SUPPORTED_MATCH")
    match_id = _required_string(selected, "match_id")
    create_url = f"{base_url}/api/v1/analyses"
    common_body: dict[str, object] = {
        "platform": platform,
        "match_id": match_id,
        "puuid": puuid,
    }
    created_zh = _request_mapping(
        client, "POST", create_url, json={**common_body, "locale": "zh-CN"}
    )
    created_en = _request_mapping(
        client, "POST", create_url, json={**common_body, "locale": "en-US"}
    )
    analysis_id = _required_string(created_zh, "analysis_id")
    loaded_url = f"{create_url}/{quote(analysis_id, safe='')}"
    loaded_zh = _request_mapping(client, "GET", loaded_url, params={"locale": "zh-CN"})
    loaded_en = _request_mapping(client, "GET", loaded_url, params={"locale": "en-US"})
    payloads = (created_zh, created_en, loaded_zh, loaded_en)
    for payload, locale in zip(
        payloads, ("zh-CN", "en-US", "zh-CN", "en-US"), strict=True
    ):
        _validate_payload(payload, expected_locale=locale)

    if created_en.get("cached") is not True:
        raise SmokeFailure("ANALYSIS_SMOKE_REPEAT_MISMATCH")
    if loaded_zh.get("cached") is not True or loaded_en.get("cached") is not True:
        raise SmokeFailure("ANALYSIS_SMOKE_REPEAT_MISMATCH")
    neutral = _neutral_result(created_zh)
    if any(_neutral_result(payload) != neutral for payload in payloads[1:]):
        raise SmokeFailure("ANALYSIS_SMOKE_RESULT_MISMATCH")

    metrics = _required_list(created_zh, "metrics")
    scores = _required_mapping(created_zh, "scores")
    dimensions = _required_list(scores, "dimensions")
    findings = _required_list(created_zh, "findings")
    goals = _required_list(created_zh, "goals")
    status = created_zh.get("status")
    if status not in {"completed", "partial"}:
        raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
    coverage = scores.get("coverage")
    if not _is_bounded_number(coverage, maximum=1):
        raise SmokeFailure("ANALYSIS_SMOKE_SCORE_INVALID")
    request_id = _safe_request_id(created_zh.get("request_id")) or "none"
    print(
        f"analysis={status} metrics={len(metrics)} dimensions={len(dimensions)} "
        f"findings={len(findings)} goals={len(goals)} "
        f"coverage={_coverage_bucket(float(coverage))} repeat=ok locales=2 "
        f"request_id={request_id} versions=ok"
    )


def _request_mapping(
    client: SmokeClient,
    method: str,
    url: str,
    *,
    params: Mapping[str, str | int] | None = None,
    json: Mapping[str, object] | None = None,
) -> dict[str, object]:
    response = client.request(method, url, params=params, json=json)
    try:
        response.raise_for_status()
    except Exception:  # noqa: BLE001 - HTTP boundary deliberately redacts details.
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 - never expose parser or body details.
            payload = None
        if isinstance(payload, Mapping):
            error = payload.get("error")
            if isinstance(error, Mapping):
                code = error.get("code")
                if isinstance(code, str) and _SAFE_CODE.fullmatch(code):
                    raise SmokeFailure(code) from None
        raise SmokeFailure("ANALYSIS_SMOKE_REQUEST_FAILED") from None
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - never expose parser or body details.
        raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE") from None
    if not isinstance(payload, Mapping):
        raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
    return {str(key): value for key, value in payload.items()}


def _validate_payload(payload: Mapping[str, object], *, expected_locale: str) -> None:
    if payload.get("locale") != expected_locale or not isinstance(
        payload.get("cached"), bool
    ):
        raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
    if payload.get("status") not in {"completed", "partial"}:
        raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
    _required_string(payload, "analysis_id")
    input_hash = _required_string(payload, "input_hash")
    if _SAFE_INPUT_HASH.fullmatch(input_hash) is None:
        raise SmokeFailure("ANALYSIS_SMOKE_VERSION_MISMATCH")
    if (
        payload.get("metric_version") != "deterministic-metrics-v1"
        or payload.get("score_version") != "deterministic-score-v1"
        or payload.get("rules_version") != "deterministic-rules-v1"
        or payload.get("schema_version") != 1
        or payload.get("scope_notice_code") != "DETERMINISTIC_DATA_COACHING_NO_AI"
    ):
        raise SmokeFailure("ANALYSIS_SMOKE_VERSION_MISMATCH")

    metrics = _required_list(payload, "metrics")
    scores = _required_mapping(payload, "scores")
    dimensions = _required_list(scores, "dimensions")
    findings = _required_list(payload, "findings")
    goals = _required_list(payload, "goals")
    if len(dimensions) != 5 or len(findings) > 3 or len(goals) > 3:
        raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
    observed_dimensions = tuple(
        item.get("dimension") if isinstance(item, Mapping) else None
        for item in dimensions
    )
    if observed_dimensions != _DIMENSIONS:
        raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
    _validate_scores(metrics=metrics, scores=scores, dimensions=dimensions)
    _validate_references(metrics=metrics, findings=findings, goals=goals)


def _validate_scores(
    *,
    metrics: list[object],
    scores: Mapping[str, object],
    dimensions: list[object],
) -> None:
    overall = scores.get("overall_score")
    if overall is not None and not _is_bounded_number(overall):
        raise SmokeFailure("ANALYSIS_SMOKE_SCORE_INVALID")
    if not _is_bounded_number(scores.get("coverage"), maximum=1):
        raise SmokeFailure("ANALYSIS_SMOKE_SCORE_INVALID")
    for dimension in dimensions:
        if not isinstance(dimension, Mapping):
            raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
        score = dimension.get("score")
        if score is not None and not _is_bounded_number(score):
            raise SmokeFailure("ANALYSIS_SMOKE_SCORE_INVALID")
        for key, maximum in (
            ("configured_weight", 100),
            ("applied_weight", 100),
            ("coverage", 1),
        ):
            if not _is_bounded_number(dimension.get(key), maximum=maximum):
                raise SmokeFailure("ANALYSIS_SMOKE_SCORE_INVALID")
    for metric in metrics:
        if not isinstance(metric, Mapping):
            raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
        comparisons = metric.get("comparisons")
        if not isinstance(comparisons, list):
            raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
        for comparison in comparisons:
            if not isinstance(comparison, Mapping) or not _is_bounded_number(
                comparison.get("score")
            ):
                raise SmokeFailure("ANALYSIS_SMOKE_SCORE_INVALID")


def _validate_references(
    *, metrics: list[object], findings: list[object], goals: list[object]
) -> None:
    catalog = {
        item.get("evidence_id")
        for item in metrics
        if isinstance(item, Mapping) and isinstance(item.get("evidence_id"), str)
    }
    if len(catalog) != len(metrics):
        raise SmokeFailure("ANALYSIS_SMOKE_EVIDENCE_MISMATCH")
    for item in (*findings, *goals):
        if not isinstance(item, Mapping):
            raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
        evidence_ids = item.get("evidence_ids")
        if not isinstance(evidence_ids, list) or any(
            not isinstance(evidence_id, str) or evidence_id not in catalog
            for evidence_id in evidence_ids
        ):
            raise SmokeFailure("ANALYSIS_SMOKE_EVIDENCE_MISMATCH")


def _neutral_result(payload: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(payload.get(field) for field in _RESULT_FIELDS)


def _is_bounded_number(value: object, *, maximum: float = 100) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and 0 <= float(value) <= maximum
    )


def _coverage_bucket(coverage: float) -> str:
    if coverage < 0.6:
        return "lt_60"
    if coverage < 0.8:
        return "60_79"
    if coverage < 1:
        return "80_99"
    return "100"


def _required_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
    return value


def _required_list(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
    return value


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")
    return value


def _safe_request_id(value: object) -> str | None:
    if isinstance(value, str) and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return None


def main() -> int:
    try:
        settings = Settings()
        require_smoke_configuration(
            game_name=settings.riot_smoke_game_name,
            tag_line=settings.riot_smoke_tag_line,
            platform=settings.riot_smoke_platform,
            riot_configured=settings.riot_configured,
            analysis_enabled=settings.deterministic_analysis_enabled,
        )
        with httpx2.Client(timeout=30.0) as client:
            run_smoke(
                client=client,
                api_base_url=settings.smoke_api_base_url,
                game_name=settings.riot_smoke_game_name,
                tag_line=settings.riot_smoke_tag_line,
                platform=settings.riot_smoke_platform,
            )
    except SmokeFailure as error:
        print(error)
        return 1
    except Exception:  # noqa: BLE001 - the process boundary must redact all unexpected details.
        print(SmokeFailure("ANALYSIS_SMOKE_REQUEST_FAILED"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
