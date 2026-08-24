"""Contracts for the deterministic-analysis Make target and privacy-safe smoke flow."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = REPOSITORY_ROOT / "scripts" / "smoke_analysis.py"
SAFE_REQUEST_ID = "a3f4c1d2e5b67890a1b2c3d4e5f60718"
ANALYSIS_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
INPUT_HASH = "a" * 64


def _load_smoke_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke_analysis", SMOKE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class FakeResponse:
    payload: object
    status_code: int = 200
    raise_error: Exception | None = None

    def raise_for_status(self) -> None:
        if self.raise_error is not None:
            raise self.raise_error
        if self.status_code >= 400:
            raise RuntimeError("raw response body")

    def json(self) -> object:
        return self.payload


@dataclass
class FakeSmokeClient:
    responses: list[FakeResponse]
    requests: list[tuple[str, str, dict[str, str | int] | None, dict[str, object] | None]] = field(
        default_factory=list
    )

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
        json: dict[str, object] | None = None,
    ) -> FakeResponse:
        self.requests.append((method, url, params, json))
        if not self.responses:
            raise AssertionError("no fake response queued")
        return self.responses.pop(0)


def _analysis_payload(*, locale: str, cached: bool) -> dict[str, object]:
    evidence_id = "metric:v1:kda"
    dimensions = [
        "economy",
        "combat",
        "survivability",
        "team_objectives",
        "vision",
    ]
    return {
        "analysis_id": ANALYSIS_ID,
        "status": "completed",
        "cached": cached,
        "locale": locale,
        "role": "support",
        "metrics": [
            {
                "evidence_id": evidence_id,
                "metric_key": "kda",
                "category": "combat",
                "status": "available",
                "value": 6.0,
                "unit": "ratio",
                "beneficial_direction": "higher",
                "comparisons": [
                    {
                        "basis": "team_percentile",
                        "score": 75.0,
                        "opponent_value": None,
                    }
                ],
                "confidence": "high",
                "source_type": "match",
                "source_fact_ids": [],
                "unavailable_reason": None,
                "metric_version": "deterministic-metrics-v1",
            }
        ],
        "scores": {
            "role": "support",
            "dimensions": [
                {
                    "dimension": dimension,
                    "status": "available",
                    "score": 80.0,
                    "configured_weight": 20.0,
                    "applied_weight": 20.0,
                    "coverage": 1.0,
                    "evidence_ids": [evidence_id],
                }
                for dimension in dimensions
            ],
            "overall_score": 80.0,
            "coverage": 0.82,
            "score_version": "deterministic-score-v1",
        },
        "findings": [
            {
                "rule_id": "finding.combat.strength",
                "kind": "strength",
                "severity": "medium",
                "message_code": "analysis.finding.combat.strength",
                "params": {"score": 80.0, "coverage": 1.0},
                "evidence_ids": [evidence_id],
                "confidence": "medium",
                "requires_replay_interpretation": False,
            }
        ],
        "goals": [
            {
                "rule_id": "goal.support.vision_per_min",
                "message_code": "analysis.goal.vision_per_min",
                "current_value": 0.8,
                "target_value": 1.2,
                "unit": "per_minute",
                "role": "support",
                "evidence_ids": [evidence_id],
                "rules_version": "deterministic-rules-v1",
            }
        ],
        "unavailable_reasons": [],
        "input_hash": INPUT_HASH,
        "metric_version": "deterministic-metrics-v1",
        "score_version": "deterministic-score-v1",
        "rules_version": "deterministic-rules-v1",
        "schema_version": 1,
        "scope_notice_code": "DETERMINISTIC_DATA_COACHING_NO_AI",
        "request_id": SAFE_REQUEST_ID,
    }


def _success_client() -> FakeSmokeClient:
    matches = [
        {
            "match_id": "NA1_newest_unsupported",
            "analysis_supported": False,
            "detail_supported": True,
        },
        {
            "match_id": "NA1_selected_private_match",
            "analysis_supported": True,
            "detail_supported": True,
        },
        {
            "match_id": "NA1_older_supported",
            "analysis_supported": True,
            "detail_supported": True,
        },
    ]
    return FakeSmokeClient(
        responses=[
            FakeResponse({"player": {"puuid": "private-puuid"}}),
            FakeResponse({"matches": matches}),
            FakeResponse(_analysis_payload(locale="zh-CN", cached=False)),
            FakeResponse(_analysis_payload(locale="en-US", cached=True)),
            FakeResponse(_analysis_payload(locale="zh-CN", cached=True)),
            FakeResponse(_analysis_payload(locale="en-US", cached=True)),
        ]
    )


def test_makefile_exposes_analysis_smoke_target() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text()
    assert "smoke-analysis:" in makefile
    assert "PYTHONPATH=backend backend/.venv/bin/python scripts/smoke_analysis.py" in makefile


@pytest.mark.parametrize(
    ("game_name", "tag_line", "analysis_enabled", "riot_configured"),
    [
        ("", "1115", True, True),
        ("Secret Player", "", True, True),
        ("Secret Player", "1115", False, True),
        ("Secret Player", "1115", True, False),
    ],
)
def test_smoke_requires_existing_riot_identity_and_enabled_analysis(
    game_name: str,
    tag_line: str,
    analysis_enabled: bool,
    riot_configured: bool,
) -> None:
    smoke = _load_smoke_module()
    with pytest.raises(smoke.SmokeFailure) as raised:
        smoke.require_smoke_configuration(
            game_name=game_name,
            tag_line=tag_line,
            platform="NA1",
            riot_configured=riot_configured,
            analysis_enabled=analysis_enabled,
        )
    assert str(raised.value) == "ANALYSIS_SMOKE_CONFIGURATION_REQUIRED"


def test_smoke_runs_bilingual_create_and_get_flow_with_safe_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    smoke = _load_smoke_module()
    client = _success_client()

    smoke.run_smoke(
        client=client,
        api_base_url="http://localhost:8000",
        game_name="Secret Player",
        tag_line="1115",
        platform="NA1",
    )

    output = capsys.readouterr().out
    assert output == (
        "analysis=completed metrics=1 dimensions=5 findings=1 goals=1 "
        "coverage=80_99 repeat=ok locales=2 "
        f"request_id={SAFE_REQUEST_ID} versions=ok\n"
    )
    methods = [request[0] for request in client.requests]
    assert methods == ["GET", "GET", "POST", "POST", "GET", "GET"]
    assert client.requests[0][2] == {
        "platform": "NA1",
        "game_name": "Secret Player",
        "tag_line": "1115",
    }
    assert client.requests[1][2] == {"platform": "NA1", "count": 10, "locale": "en-US"}
    assert client.requests[2][3] == {
        "platform": "NA1",
        "match_id": "NA1_selected_private_match",
        "puuid": "private-puuid",
        "locale": "zh-CN",
    }
    assert client.requests[3][3] == {**client.requests[2][3], "locale": "en-US"}
    assert client.requests[4][2] == {"locale": "zh-CN"}
    assert client.requests[5][2] == {"locale": "en-US"}
    for sensitive in (
        "Secret Player",
        "1115",
        "private-puuid",
        "NA1_selected_private_match",
        "RGAPI-private-key",
        "http://localhost:8000",
        "metric:v1:kda",
        ANALYSIS_ID,
        INPUT_HASH,
    ):
        assert sensitive not in output


def test_smoke_rejects_locale_neutral_result_drift() -> None:
    smoke = _load_smoke_module()
    client = _success_client()
    second_create = client.responses[3].payload
    assert isinstance(second_create, dict)
    second_create["role"] = "top"

    with pytest.raises(smoke.SmokeFailure) as raised:
        smoke.run_smoke(
            client=client,
            api_base_url="http://localhost:8000",
            game_name="Secret Player",
            tag_line="1115",
            platform="NA1",
        )
    assert str(raised.value) == "ANALYSIS_SMOKE_RESULT_MISMATCH"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("missing_reference", "ANALYSIS_SMOKE_EVIDENCE_MISMATCH"),
        ("score_out_of_range", "ANALYSIS_SMOKE_SCORE_INVALID"),
        ("second_not_cached", "ANALYSIS_SMOKE_REPEAT_MISMATCH"),
    ],
)
def test_smoke_rejects_broken_result_contract(mutation: str, expected_code: str) -> None:
    smoke = _load_smoke_module()
    client = _success_client()
    payload = client.responses[2].payload
    assert isinstance(payload, dict)
    if mutation == "missing_reference":
        findings = payload["findings"]
        assert isinstance(findings, list) and isinstance(findings[0], dict)
        findings[0]["evidence_ids"] = ["private-missing-evidence"]
    elif mutation == "score_out_of_range":
        scores = payload["scores"]
        assert isinstance(scores, dict)
        scores["overall_score"] = 101
    else:
        second = client.responses[3].payload
        assert isinstance(second, dict)
        second["cached"] = False

    with pytest.raises(smoke.SmokeFailure) as raised:
        smoke.run_smoke(
            client=client,
            api_base_url="http://localhost:8000",
            game_name="Secret Player",
            tag_line="1115",
            platform="NA1",
        )
    assert str(raised.value) == expected_code


def test_unexpected_exception_collapses_without_url_or_response_body() -> None:
    smoke = _load_smoke_module()

    class ExplodingClient:
        def request(self, *_args: object, **_kwargs: object) -> FakeResponse:
            raise RuntimeError(
                "http://localhost:8000 Secret Player private-puuid RGAPI-private-key raw body"
            )

    with pytest.raises(smoke.SmokeFailure) as raised:
        smoke.run_smoke(
            client=ExplodingClient(),
            api_base_url="http://localhost:8000",
            game_name="Secret Player",
            tag_line="1115",
            platform="NA1",
        )
    assert str(raised.value) == "ANALYSIS_SMOKE_REQUEST_FAILED"
    assert "http" not in str(raised.value)


def test_smoke_failure_allows_only_stable_uppercase_codes() -> None:
    smoke = _load_smoke_module()
    assert str(smoke.SmokeFailure("ANALYSIS_SMOKE_INVALID_RESPONSE")) == (
        "ANALYSIS_SMOKE_INVALID_RESPONSE"
    )
    with pytest.raises(ValueError):
        smoke.SmokeFailure("unsafe private-puuid")
