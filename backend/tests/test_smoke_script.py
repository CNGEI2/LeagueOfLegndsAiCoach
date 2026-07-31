from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.services.riot.smoke import SmokeFailure, require_smoke_configuration, run_smoke


@dataclass
class FakeResponse:
    payload: object
    status_code: int = 200
    raise_error: Exception | None = None

    def raise_for_status(self) -> None:
        if self.raise_error is not None:
            raise self.raise_error

    def json(self) -> object:
        return self.payload


@dataclass
class FakeSmokeClient:
    responses: list[FakeResponse]
    requests: list[tuple[str, dict[str, str | int]]] = field(default_factory=list)

    def get(self, url: str, *, params: dict[str, str | int]) -> FakeResponse:
        self.requests.append((url, params))
        return self.responses.pop(0)


def _success_client(*, matches: list[dict[str, object]] | None = None) -> FakeSmokeClient:
    recent_matches = matches or [
        {"match_id": "NA1_123456789", "detail_supported": True},
        {"match_id": "NA1_123456788", "detail_supported": False},
        {"match_id": "NA1_123456787", "detail_supported": True},
    ]
    return FakeSmokeClient(
        responses=[
            FakeResponse({"player": {"puuid": "private-puuid"}}),
            FakeResponse({"matches": recent_matches}),
            FakeResponse({"match_id": "NA1_123456789"}),
            FakeResponse({"match_id": "NA1_123456789"}),
            FakeResponse({"matches": recent_matches}),
        ]
    )


def test_smoke_reports_generic_counts_without_identifier_or_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Changing the success output to include a request value must fail this safety contract."""
    client = _success_client()

    run_smoke(
        client=client,
        api_base_url="http://localhost:8000",
        game_name="Secret Player",
        tag_line="1115",
        platform="NA1",
    )

    output = capsys.readouterr().out
    assert output == "Phase 2 Riot smoke passed: matches=3 locales=2 repeat=ok\n"
    for sensitive_value in (
        "Secret Player",
        "1115",
        "private-puuid",
        "NA1_123456789",
        "RGAPI-private-key",
        "http://localhost:8000",
    ):
        assert sensitive_value not in output


def test_smoke_queries_both_locales_then_repeats_recent_matches() -> None:
    """Removing either localized detail request or the cache repeat must fail acceptance."""
    client = _success_client()

    run_smoke(
        client=client,
        api_base_url="http://localhost:8000",
        game_name="Secret Player",
        tag_line="1115",
        platform="NA1",
    )

    assert [request[1].get("locale") for request in client.requests] == [
        None,
        "en-US",
        "en-US",
        "zh-CN",
        "en-US",
    ]
    assert client.requests[2][0] == client.requests[3][0]
    assert client.requests[1][0] == client.requests[4][0]


@pytest.mark.parametrize(
    ("game_name", "tag_line", "riot_configured"),
    [
        ("", "1115", True),
        ("Secret Player", "", True),
        ("Secret Player", "1115", False),
    ],
)
def test_smoke_requires_nonempty_identity_and_configured_riot_key(
    game_name: str, tag_line: str, riot_configured: bool
) -> None:
    """Removing smoke configuration validation would allow an unsafe or useless live request."""
    with pytest.raises(SmokeFailure) as caught:
        require_smoke_configuration(
            game_name=game_name,
            tag_line=tag_line,
            platform="NA1",
            riot_configured=riot_configured,
        )

    assert caught.value.code == "SMOKE_CONFIGURATION_REQUIRED"
    assert caught.value.request_id is None


def test_smoke_rejects_puuid_like_error_request_id_without_losing_safe_code() -> None:
    """Relaxing request-ID validation would print an attacker-controlled identifier."""
    sensitive_puuid = "private-puuid-1"
    client = FakeSmokeClient(
        responses=[
            FakeResponse(
                {
                    "error": {
                        "code": "PLAYER_NOT_FOUND",
                        "request_id": sensitive_puuid,
                    }
                },
                raise_error=RuntimeError("request failed"),
            )
        ]
    )

    with pytest.raises(SmokeFailure) as caught:
        run_smoke(
            client=client,
            api_base_url="http://localhost:8000",
            game_name="Secret Player",
            tag_line="1115",
            platform="NA1",
        )

    assert caught.value.code == "PLAYER_NOT_FOUND"
    assert caught.value.request_id is None
    assert sensitive_puuid not in str(caught.value)


@pytest.mark.parametrize(
    ("responses", "expected_code", "expected_request_id"),
    [
        (
            [
                FakeResponse(
                    {
                        "error": {
                            "code": "PLAYER_NOT_FOUND",
                            "request_id": "0123456789abcdef0123456789abcdef",
                            "message": "Secret Player RGAPI-private-key",
                        }
                    },
                    raise_error=RuntimeError("http://localhost:8000/private-puuid"),
                )
            ],
            "PLAYER_NOT_FOUND",
            "0123456789abcdef0123456789abcdef",
        ),
        (
            [
                FakeResponse({"player": {"puuid": "private-puuid"}}),
                FakeResponse({"matches": []}),
            ],
            "SMOKE_NO_RECENT_MATCHES",
            None,
        ),
        (
            [
                FakeResponse({"player": {"puuid": "private-puuid"}}),
                FakeResponse(
                    {"matches": [{"match_id": "NA1_123456789", "detail_supported": False}]}
                ),
            ],
            "SMOKE_NO_DETAIL_SUPPORTED_MATCH",
            None,
        ),
        (
            [
                FakeResponse({"player": {"puuid": "private-puuid"}}),
                FakeResponse(
                    {"matches": [{"match_id": "NA1_123456789", "detail_supported": True}]}
                ),
                FakeResponse(
                    {
                        "error": {
                            "code": "MATCH_NOT_FOUND",
                            "request_id": "fedcba9876543210fedcba9876543210",
                            "message": "NA1_123456789",
                        }
                    },
                    raise_error=RuntimeError("raw response body"),
                ),
            ],
            "MATCH_NOT_FOUND",
            "fedcba9876543210fedcba9876543210",
        ),
        (
            [FakeResponse("RGAPI-private-key http://localhost:8000/private-puuid")],
            "SMOKE_INVALID_RESPONSE",
            None,
        ),
    ],
)
def test_smoke_redacts_failures_to_stable_code_and_request_id(
    responses: list[FakeResponse], expected_code: str, expected_request_id: str | None
) -> None:
    """Leaking backend bodies, URLs, or exception strings must fail this error-boundary test."""
    client = FakeSmokeClient(responses=responses)

    with pytest.raises(SmokeFailure) as caught:
        run_smoke(
            client=client,
            api_base_url="http://localhost:8000",
            game_name="Secret Player",
            tag_line="1115",
            platform="NA1",
        )

    assert caught.value.code == expected_code
    assert caught.value.request_id == expected_request_id
    rendered = str(caught.value)
    for sensitive_value in (
        "Secret Player",
        "1115",
        "private-puuid",
        "NA1_123456789",
        "RGAPI-private-key",
        "http://localhost:8000",
        "raw response body",
    ):
        assert sensitive_value not in rendered
