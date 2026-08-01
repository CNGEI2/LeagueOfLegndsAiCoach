from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dependencies import AppServices
from app.main import create_app
from app.schemas.replays import (
    ReplayArtifactAccess,
    ReplayArtifactResponse,
    ReplayCreateData,
    ReplayCreateRequest,
    ReplayRetentionInfo,
    ReplayStatusData,
    ReplayUploadInfo,
)
from app.services.replays.domain import ReplayArtifactKind, ReplayStatus
from tests.conftest import FakeDatabase
from tests.test_replay_api import ControllableReplayService

NOW = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
REPLAY_ID = uuid4()
ARTIFACT_ID = uuid4()
TOKEN = "privacy-token-once"

FORBIDDEN_FRAGMENTS = (
    "token_digest",
    "selected_puuid",
    "object_key",
    "source_object_key",
    "original_filename",
    "owned recording.mp4",
    "/var/replays",
    "ffmpeg",
    "ffprobe",
    "Input #0",
    str(Path("/tmp/secret-replay-path")),
)


class PrivacyReplayService(ControllableReplayService):
    def __init__(self) -> None:
        super().__init__()
        self.create_result = ReplayCreateData(
            replay_id=REPLAY_ID,
            access_token=TOKEN,
            status=ReplayStatus.CREATED,
            upload=ReplayUploadInfo(
                method="PUT",
                url=f"/api/v1/replays/{REPLAY_ID}/content",
                headers={},
                expires_at=NOW + timedelta(minutes=30),
            ),
            retention=ReplayRetentionInfo(
                source_hours_after_processing=24,
                derived_days_after_ready=7,
            ),
        )
        self.status_result = ReplayStatusData(
            replay_id=REPLAY_ID,
            status=ReplayStatus.FAILED,
            processing_stage=None,
            progress_percent=0,
            normalized_duration_ms=None,
            width=None,
            height=None,
            available_game_time_start_ms=None,
            available_game_time_end_ms=None,
            warning_codes=(),
            error_code="REPLAY_MEDIA_UNSUPPORTED",
            error_retryable=False,
            source_delete_after=NOW + timedelta(hours=24),
            derived_delete_after=None,
        )
        self.authorize_row.id = REPLAY_ID
        self.authorize_row.selected_puuid = "selected-player-puuid"
        self.authorize_row.token_digest = "super-secret-digest"
        self.authorize_row.original_filename = "owned recording.mp4"
        self.authorize_row.source_object_key = "source/abc/input"
        self.artifacts = [
            ReplayArtifactResponse(
                artifact_id=ARTIFACT_ID,
                replay_id=REPLAY_ID,
                kind=ReplayArtifactKind.ANCHOR_FRAME,
                game_time_ms=0,
                video_time_ms=1000,
                media_type="image/jpeg",
                width=640,
                height=360,
                size_bytes=512,
                access=ReplayArtifactAccess(
                    mode="bearer",
                    url=f"/api/v1/replays/{REPLAY_ID}/artifacts/{ARTIFACT_ID}/content",
                    expires_at=NOW + timedelta(minutes=5),
                ),
            )
        ]

    async def authorize(self, replay_id: UUID, token: str):  # type: ignore[override]
        if token != TOKEN or replay_id != REPLAY_ID:
            from app.core.errors import ApiError

            raise ApiError(
                status_code=404,
                code="REPLAY_NOT_FOUND",
                message="The requested replay was not found.",
                retryable=False,
            )
        return self.authorize_row

    async def create(
        self, request: ReplayCreateRequest, *, now: datetime | None = None
    ) -> ReplayCreateData:
        del request, now
        return self.create_result


@pytest.fixture
def privacy_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        backend_cors_origins="http://localhost:3000",
        riot_api_key="RGAPI-test",
        replay_enabled=True,
        replay_token_secret="x" * 32,
        replay_local_root=tmp_path,
    )
    service = PrivacyReplayService()
    services = AppServices(
        player_service=object(),  # type: ignore[arg-type]
        match_service=object(),  # type: ignore[arg-type]
        replay_service=service,  # type: ignore[arg-type]
        closers=(),
    )
    with TestClient(
        create_app(settings=settings, database=FakeDatabase(), services=services)
    ) as client:
        yield client


def _assert_private(text: str) -> None:
    lowered = text.lower()
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment.lower() not in lowered


def test_replay_api_responses_never_leak_sensitive_fields(
    privacy_client: TestClient,
) -> None:
    create = privacy_client.post(
        "/api/v1/replays",
        json={
            "match_id": "NA1_1234567890",
            "platform": "NA1",
            "puuid": "selected-player-puuid",
            "original_filename": "owned recording.mp4",
            "declared_size_bytes": 123456,
            "declared_content_type": "video/mp4",
            "game_time_zero_ms": 1000,
            "rights_attested": True,
            "rights_statement_version": "2026-08-01",
        },
    )
    assert create.status_code == 201
    _assert_private(create.text)
    assert create.json()["access_token"] == TOKEN

    headers = {"Authorization": f"Bearer {TOKEN}"}
    status = privacy_client.get(f"/api/v1/replays/{REPLAY_ID}", headers=headers)
    assert status.status_code == 200
    _assert_private(status.text)

    artifacts = privacy_client.get(f"/api/v1/replays/{REPLAY_ID}/artifacts", headers=headers)
    assert artifacts.status_code == 200
    _assert_private(artifacts.text)

    complete = privacy_client.post(f"/api/v1/replays/{REPLAY_ID}/complete", headers=headers)
    assert complete.status_code == 200
    _assert_private(complete.text)

    retry = privacy_client.post(f"/api/v1/replays/{REPLAY_ID}/retry", headers=headers)
    assert retry.status_code == 200
    _assert_private(retry.text)

    delete = privacy_client.delete(f"/api/v1/replays/{REPLAY_ID}", headers=headers)
    assert delete.status_code == 200
    _assert_private(delete.text)

    missing = privacy_client.get(
        f"/api/v1/replays/{REPLAY_ID}",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert missing.status_code == 404
    _assert_private(missing.text)
    assert "wrong-token" not in missing.text
