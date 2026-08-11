from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import AppServices
from app.core.errors import ApiError
from app.core.routing import Platform
from app.main import create_app
from app.schemas.domain import Locale, StaticDataStatus
from app.schemas.evidence import (
    JointEvidenceData,
    PublicChampionKillFact,
    ReplayLinkSummary,
)
from app.services.evidence.service import DisabledJointEvidenceService
from tests.conftest import (
    FakeDatabase,
    FakeMatchService,
    FakePlatformDetectionService,
    FakePlayerService,
    FakeReplayService,
)

PUUID = "selected-player-puuid"
MATCH_ID = "NA1_fixture"
TOKEN = "capability-token-value"


class FakeJointEvidenceService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.error: ApiError | None = None
        self.data = JointEvidenceData(
            platform=Platform.NA1,
            match_id=MATCH_ID,
            locale=Locale.EN_US,
            schema_version=1,
            facts=(
                PublicChampionKillFact(
                    fact_id="timeline:NA1:NA1_fixture:v1:frame:1:event:0",
                    kind="champion_kill",
                    timestamp_ms=60_000,
                    relationship="killer",
                    killer_id=1,
                    victim_id=6,
                    assisting_participant_ids=(),
                    position_x=1,
                    position_y=2,
                ),
            ),
            windows=(),
            timeline_cache_status="miss",
            replay_link=None,
            static_data_status=StaticDataStatus(available=True, version="16.15.2", code=None),
            truncated=False,
            total_window_count=0,
        )

    async def prepare(self, *, match_id: str, request: object, replay_token: str | None):
        self.calls.append({"match_id": match_id, "request": request, "replay_token": replay_token})
        if self.error is not None:
            raise self.error
        locale = getattr(request, "locale", Locale.EN_US)
        platform = getattr(request, "platform", Platform.NA1)
        return self.data.model_copy(
            update={"locale": locale, "platform": platform, "match_id": match_id}
        )


@pytest.fixture
def evidence_client() -> Generator[tuple[TestClient, FakeJointEvidenceService], None, None]:
    joint = FakeJointEvidenceService()
    services = AppServices(
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=FakePlatformDetectionService(),
        joint_evidence_service=joint,
        closers=(),
    )
    application = create_app(
        settings=__import__("app.core.config", fromlist=["Settings"]).Settings(
            _env_file=None,
            app_env="test",
            database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
            riot_api_key="RGAPI-test",
            joint_evidence_enabled=True,
        ),
        database=FakeDatabase(),
        services=services,
    )
    with TestClient(application) as client:
        yield client, joint


@pytest.fixture
def disabled_client() -> Generator[TestClient, None, None]:
    services = AppServices(
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=FakePlatformDetectionService(),
        joint_evidence_service=DisabledJointEvidenceService(),
        closers=(),
    )
    application = create_app(
        settings=__import__("app.core.config", fromlist=["Settings"]).Settings(
            _env_file=None,
            app_env="test",
            database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
            riot_api_key="RGAPI-test",
            joint_evidence_enabled=False,
        ),
        database=FakeDatabase(),
        services=services,
    )
    with TestClient(application) as client:
        yield client


def test_evidence_rejects_unknown_fields(
    evidence_client: tuple[TestClient, FakeJointEvidenceService],
) -> None:
    client, joint = evidence_client
    response = client.post(
        f"/api/v1/matches/{MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": PUUID, "coaching": True},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert joint.calls == []


def test_evidence_rejects_oversized_match_id_path(
    evidence_client: tuple[TestClient, FakeJointEvidenceService],
) -> None:
    client, _ = evidence_client
    response = client.post(
        f"/api/v1/matches/{'x' * 65}/evidence",
        json={"platform": "NA1", "puuid": PUUID},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("platform", list(Platform))
def test_evidence_accepts_all_platforms(
    evidence_client: tuple[TestClient, FakeJointEvidenceService], platform: Platform
) -> None:
    client, joint = evidence_client
    response = client.post(
        f"/api/v1/matches/{MATCH_ID}/evidence",
        json={"platform": platform.value, "puuid": PUUID, "locale": "zh-CN"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["locale"] == "zh-CN"
    assert body["scope_notice_code"] == "EVIDENCE_ONLY_NO_COACHING"
    assert joint.calls[-1]["request"].platform == platform  # type: ignore[attr-defined]


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_evidence_accepts_supported_locales(
    evidence_client: tuple[TestClient, FakeJointEvidenceService], locale: str
) -> None:
    client, _ = evidence_client
    response = client.post(
        f"/api/v1/matches/{MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": PUUID, "locale": locale},
    )
    assert response.status_code == 200
    assert response.json()["locale"] == locale


def test_evidence_disabled_returns_not_found(disabled_client: TestClient) -> None:
    response = disabled_client.post(
        f"/api/v1/matches/{MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": PUUID},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_evidence_authorization_rules(
    evidence_client: tuple[TestClient, FakeJointEvidenceService],
) -> None:
    client, joint = evidence_client
    ok = client.post(
        f"/api/v1/matches/{MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": PUUID, "replay_id": None},
    )
    assert ok.status_code == 200
    assert joint.calls[-1]["replay_token"] is None

    forbidden = client.post(
        f"/api/v1/matches/{MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": PUUID},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert forbidden.status_code == 422
    assert forbidden.json()["error"]["code"] == "VALIDATION_ERROR"
    assert TOKEN not in forbidden.text

    replay_id = str(uuid4())
    missing = client.post(
        f"/api/v1/matches/{MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": PUUID, "replay_id": replay_id},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "REPLAY_NOT_FOUND"

    linked = client.post(
        f"/api/v1/matches/{MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": PUUID, "replay_id": replay_id},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert linked.status_code == 200
    received = joint.calls[-1]["replay_token"]
    assert isinstance(received, str)
    assert __import__("hmac").compare_digest(received, TOKEN)
    assert TOKEN not in linked.text
    body = linked.json()
    assert "puuid" not in body
    assert "object_key" not in linked.text
    assert "access_token" not in linked.text


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (
            ApiError(
                status_code=404,
                code="MATCH_NOT_FOUND",
                message="The requested match was not found.",
                retryable=False,
            ),
            404,
        ),
        (
            ApiError(
                status_code=404,
                code="PLAYER_NOT_IN_MATCH",
                message="The selected player did not participate in this match.",
                retryable=False,
            ),
            404,
        ),
        (
            ApiError(
                status_code=422,
                code="MATCH_EVIDENCE_UNSUPPORTED_MODE",
                message="Match evidence is not supported for this game mode.",
                retryable=False,
            ),
            422,
        ),
        (
            ApiError(
                status_code=404,
                code="MATCH_TIMELINE_NOT_FOUND",
                message="The requested match timeline was not found.",
                retryable=False,
            ),
            404,
        ),
        (
            ApiError(
                status_code=404,
                code="REPLAY_NOT_FOUND",
                message="The requested replay was not found.",
                retryable=False,
            ),
            404,
        ),
        (
            ApiError(
                status_code=409,
                code="REPLAY_EVIDENCE_NOT_READY",
                message="The replay is not ready for evidence linkage.",
                retryable=True,
            ),
            409,
        ),
        (
            ApiError(
                status_code=503,
                code="RIOT_AUTH_FAILED",
                message="Riot authentication failed.",
                retryable=False,
            ),
            503,
        ),
        (
            ApiError(
                status_code=429,
                code="RIOT_RATE_LIMITED",
                message="Riot rate limited the request.",
                retryable=True,
            ),
            429,
        ),
        (
            ApiError(
                status_code=502,
                code="RIOT_INVALID_RESPONSE",
                message="Riot returned an invalid response.",
                retryable=False,
            ),
            502,
        ),
        (
            ApiError(
                status_code=503,
                code="RIOT_UNAVAILABLE",
                message="Riot is temporarily unavailable.",
                retryable=True,
            ),
            503,
        ),
    ],
)
def test_evidence_maps_approved_errors(
    evidence_client: tuple[TestClient, FakeJointEvidenceService],
    error: ApiError,
    status: int,
) -> None:
    client, joint = evidence_client
    joint.error = error
    response = client.post(
        f"/api/v1/matches/{MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": PUUID},
    )
    assert response.status_code == status
    payload = response.json()["error"]
    assert payload["code"] == error.code
    assert payload["retryable"] is error.retryable
    assert payload["request_id"] == response.headers["X-Request-ID"]


def test_evidence_success_body_is_strict(
    evidence_client: tuple[TestClient, FakeJointEvidenceService],
) -> None:
    client, joint = evidence_client
    joint.data = joint.data.model_copy(
        update={
            "replay_link": ReplayLinkSummary(full_count=1, partial_count=0, unavailable_count=0)
        }
    )
    response = client.post(
        f"/api/v1/matches/{MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": PUUID, "locale": "en-US"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["schema_version"] == 1
    assert body["replay_link"] == {
        "status": "linked",
        "full_count": 1,
        "partial_count": 0,
        "unavailable_count": 0,
    }
    assert set(body.keys()) >= {
        "status",
        "platform",
        "match_id",
        "locale",
        "schema_version",
        "facts",
        "windows",
        "timeline_cache_status",
        "replay_link",
        "static_data_status",
        "truncated",
        "total_window_count",
        "scope_notice_code",
        "request_id",
    }
    assert "puuid" not in body
    assert "selected_puuid" not in body


@pytest.mark.parametrize(
    "authorization",
    [
        "Basic not-a-bearer",
        "Bearer ",
        "Bearer tok en",
        "Bearer " + ("x" * 513),
    ],
)
def test_evidence_replay_bearer_rejects_malformed_empty_and_oversized(
    evidence_client: tuple[TestClient, FakeJointEvidenceService],
    authorization: str,
) -> None:

    client, joint = evidence_client
    replay_id = str(uuid4())
    response = client.post(
        f"/api/v1/matches/{MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": PUUID, "replay_id": replay_id},
        headers={"Authorization": authorization},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPLAY_NOT_FOUND"
    assert joint.calls == []
    assert authorization not in response.text
    assert authorization not in response.json()["error"]["message"]


def test_evidence_replay_accepts_exact_512_byte_bearer_without_leaking_token(
    evidence_client: tuple[TestClient, FakeJointEvidenceService],
) -> None:
    import hmac

    client, joint = evidence_client
    token = "z" * 512
    replay_id = str(uuid4())
    response = client.post(
        f"/api/v1/matches/{MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": PUUID, "replay_id": replay_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(joint.calls) == 1
    received = joint.calls[0]["replay_token"]
    assert isinstance(received, str)
    assert hmac.compare_digest(received, token)
    assert token not in response.text
    assert token not in repr(response.json())
