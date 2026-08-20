from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.config import Settings
from app.core.dependencies import AppServices
from app.core.errors import ApiError, api_error_handler
from app.core.metrics import MetricsRegistry
from app.core.routing import Platform
from app.main import create_app
from app.models.timeline import MatchTimelineRow
from app.schemas.domain import Locale, StaticDataStatus
from app.schemas.evidence import JointEvidenceData, PublicChampionKillFact
from app.services.evidence.service import DisabledJointEvidenceService
from app.services.timelines.domain import TimelineSnapshot
from tests.conftest import (
    FakeDatabase,
    FakeMatchService,
    FakePlatformDetectionService,
    FakePlayerService,
    FakeReplayService,
)

SENTINEL_API_KEY = "RGAPI-sentinel-private-key"
SENTINEL_PUUID = "sentinel-puuid-value"
SENTINEL_MATCH_ID = "NA1_SENTINEL_MATCH"
SENTINEL_REPLAY_ID = str(uuid4())
SENTINEL_TOKEN = "sentinel-possession-token"
SENTINEL_OBJECT_KEY = "source/sentinel/object-key"
SENTINEL_PRESIGNED_URL = "https://cdn.example/sentinel-presigned-url"
SENTINEL_RAW_EVENT = "CHAMPION_SPECIAL_KILL"
SAFE_REQUEST_ID = "a3f4c1d2e5b67890a1b2c3d4e5f60718"

J1_ERRORS = (
    ApiError(status_code=404, code="NOT_FOUND", message="Not found.", retryable=False),
    ApiError(status_code=404, code="MATCH_NOT_FOUND", message="Match missing.", retryable=False),
    ApiError(
        status_code=404,
        code="PLAYER_NOT_IN_MATCH",
        message="Player missing.",
        retryable=False,
    ),
    ApiError(
        status_code=422,
        code="MATCH_EVIDENCE_UNSUPPORTED_MODE",
        message="Unsupported mode.",
        retryable=False,
    ),
    ApiError(
        status_code=404,
        code="MATCH_TIMELINE_NOT_FOUND",
        message="Timeline missing.",
        retryable=False,
    ),
    ApiError(status_code=404, code="REPLAY_NOT_FOUND", message="Replay missing.", retryable=False),
    ApiError(
        status_code=409,
        code="REPLAY_EVIDENCE_NOT_READY",
        message="Replay not ready.",
        retryable=True,
    ),
    ApiError(status_code=502, code="RIOT_AUTH_FAILED", message="Auth failed.", retryable=False),
    ApiError(status_code=429, code="RIOT_RATE_LIMITED", message="Rate limited.", retryable=True),
    ApiError(
        status_code=502,
        code="RIOT_INVALID_RESPONSE",
        message="Invalid Riot.",
        retryable=False,
    ),
    ApiError(status_code=503, code="RIOT_UNAVAILABLE", message="Unavailable.", retryable=True),
)


class RecordingJointEvidenceService:
    def __init__(self) -> None:
        self.error: ApiError | None = None
        self.data = JointEvidenceData(
            platform=Platform.NA1,
            match_id=SENTINEL_MATCH_ID,
            locale=Locale.EN_US,
            schema_version=1,
            facts=(
                PublicChampionKillFact(
                    fact_id="timeline:NA1:fixture:v1:frame:1:event:0",
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
        del match_id, request
        if replay_token == SENTINEL_TOKEN:
            pass
        if self.error is not None:
            raise self.error
        return self.data


def _forbidden_fragments() -> tuple[str, ...]:
    return (
        SENTINEL_API_KEY,
        SENTINEL_PUUID,
        SENTINEL_TOKEN,
        SENTINEL_OBJECT_KEY,
        SENTINEL_PRESIGNED_URL,
        SENTINEL_RAW_EVENT,
        "selected_puuid",
        "object_key",
        "access_token",
        "raw_payload",
        "raw_response",
        "presigned_url",
    )


def _assert_private(text: str) -> None:
    lowered = text.lower()
    for fragment in _forbidden_fragments():
        assert fragment.lower() not in lowered


@pytest.fixture
def privacy_client() -> Generator[
    tuple[TestClient, RecordingJointEvidenceService, MetricsRegistry], None, None
]:
    joint = RecordingJointEvidenceService()
    registry = MetricsRegistry()
    services = AppServices(
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=FakePlatformDetectionService(),
        joint_evidence_service=joint,
        closers=(),
    )
    application = create_app(
        settings=Settings(
            _env_file=None,
            app_env="test",
            database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
            riot_api_key=SENTINEL_API_KEY,
            joint_evidence_enabled=True,
        ),
        database=FakeDatabase(),
        services=services,
        replay_metrics=registry,
    )
    with TestClient(application) as client:
        yield client, joint, registry


def test_success_and_j1_error_surfaces_omit_sentinels(
    privacy_client: tuple[TestClient, RecordingJointEvidenceService, MetricsRegistry],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, joint, registry = privacy_client
    caplog.set_level("INFO")

    success = client.post(
        f"/api/v1/matches/{SENTINEL_MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": SENTINEL_PUUID, "replay_id": None},
    )
    assert success.status_code == 200
    body = success.json()
    assert "puuid" not in body
    assert "selected_puuid" not in body
    _assert_private(success.text)
    _assert_private(registry.render_prometheus_text())
    _assert_private(caplog.text)

    validation = client.post(
        f"/api/v1/matches/{SENTINEL_MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": SENTINEL_PUUID, "coaching": True},
    )
    assert validation.status_code == 422
    _assert_private(validation.text)

    auth_without_id = client.post(
        f"/api/v1/matches/{SENTINEL_MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": SENTINEL_PUUID},
        headers={"Authorization": f"Bearer {SENTINEL_TOKEN}"},
    )
    assert auth_without_id.status_code == 422
    _assert_private(auth_without_id.text)
    assert SENTINEL_TOKEN not in auth_without_id.text

    bad_bearer = client.post(
        f"/api/v1/matches/{SENTINEL_MATCH_ID}/evidence",
        json={"platform": "NA1", "puuid": SENTINEL_PUUID, "replay_id": SENTINEL_REPLAY_ID},
        headers={"Authorization": f"Bearer {SENTINEL_TOKEN}"},
    )
    # Token is accepted at the HTTP boundary and forwarded; the fake service succeeds.
    _assert_private(bad_bearer.text)
    assert SENTINEL_TOKEN not in bad_bearer.text
    assert SENTINEL_OBJECT_KEY not in bad_bearer.text
    assert SENTINEL_PRESIGNED_URL not in bad_bearer.text

    for error in J1_ERRORS:
        joint.error = error
        response = client.post(
            f"/api/v1/matches/{SENTINEL_MATCH_ID}/evidence",
            json={"platform": "NA1", "puuid": SENTINEL_PUUID},
        )
        assert response.status_code == error.status_code
        payload = response.json()
        assert payload["error"]["code"] == error.code
        _assert_private(response.text)
        _assert_private(registry.render_prometheus_text())
        _assert_private(caplog.text)
        assert SENTINEL_API_KEY not in response.text
        assert SENTINEL_TOKEN not in response.text
        assert SENTINEL_OBJECT_KEY not in response.text
        assert SENTINEL_PRESIGNED_URL not in response.text
        assert SENTINEL_RAW_EVENT not in response.text


def test_disabled_flag_not_found_omits_sentinels() -> None:
    registry = MetricsRegistry()
    services = AppServices(
        player_service=FakePlayerService(),
        match_service=FakeMatchService(),
        replay_service=FakeReplayService(),
        platform_detection_service=FakePlatformDetectionService(),
        joint_evidence_service=DisabledJointEvidenceService(),
        closers=(),
    )
    application = create_app(
        settings=Settings(
            _env_file=None,
            app_env="test",
            database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
            riot_api_key=SENTINEL_API_KEY,
            joint_evidence_enabled=False,
        ),
        database=FakeDatabase(),
        services=services,
        replay_metrics=registry,
    )
    with TestClient(application) as client:
        response = client.post(
            f"/api/v1/matches/{SENTINEL_MATCH_ID}/evidence",
            json={"platform": "NA1", "puuid": SENTINEL_PUUID, "replay_id": SENTINEL_REPLAY_ID},
            headers={"Authorization": f"Bearer {SENTINEL_TOKEN}"},
        )
    assert response.status_code == 404
    _assert_private(response.text)
    _assert_private(registry.render_prometheus_text())
    assert SENTINEL_TOKEN not in response.text


@pytest.mark.asyncio
async def test_error_handler_without_asgi_method_still_redacts_exception_text() -> None:
    request = Request({"type": "http", "state": {"request_id": SAFE_REQUEST_ID}})

    response = await api_error_handler(request, RuntimeError(SENTINEL_TOKEN))

    assert response.status_code == 500
    _assert_private(response.body.decode())
    assert SENTINEL_TOKEN not in response.body.decode()
    assert b"INTERNAL_SERVER_ERROR" in response.body


def test_timeline_cache_persists_only_normalized_snapshot_without_raw_events() -> None:
    column_names = {column.name for column in MatchTimelineRow.__table__.columns}
    assert "normalized_snapshot" in column_names
    assert "raw_payload" not in column_names
    assert "raw_response" not in column_names
    assert "events" not in column_names
    snapshot_fields = set(TimelineSnapshot.model_fields)
    assert snapshot_fields == {
        "platform",
        "match_id",
        "schema_version",
        "frame_interval_ms",
        "participant_puuids",
        "facts",
    }
    assert "events" not in snapshot_fields
    assert "participantFrames" not in snapshot_fields
    assert "raw_payload" not in snapshot_fields
