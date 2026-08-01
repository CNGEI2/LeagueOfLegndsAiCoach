from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.dependencies import AppServices
from app.core.errors import ApiError
from app.main import create_app
from app.models.replay import ReplayUploadRow
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
from app.services.replays.service import ReplayArtifactContent
from app.services.replays.storage.local import LocalReplayStorage
from tests.conftest import FakeDatabase

NOW = datetime(2026, 8, 1, 15, 0, tzinfo=UTC)
REPLAY_ID = uuid4()
ARTIFACT_ID = uuid4()
TOKEN = "returned-once"
VALID_PAYLOAD = {
    "match_id": "NA1_1234567890",
    "platform": "NA1",
    "puuid": "selected-player-puuid",
    "original_filename": "recording.mp4",
    "declared_size_bytes": 1_000_000,
    "declared_content_type": "video/mp4",
    "game_time_zero_ms": 48231,
    "rights_attested": True,
    "rights_statement_version": "2026-08-01",
}


def _status_data(
    *,
    replay_id: UUID = REPLAY_ID,
    status: ReplayStatus = ReplayStatus.QUEUED,
) -> ReplayStatusData:
    return ReplayStatusData(
        replay_id=replay_id,
        status=status,
        processing_stage=None,
        progress_percent=0,
        normalized_duration_ms=None,
        width=None,
        height=None,
        available_game_time_start_ms=None,
        available_game_time_end_ms=None,
        warning_codes=(),
        error_code=None,
        error_retryable=None,
        source_delete_after=None,
        derived_delete_after=None,
    )


def _upload_row(
    *,
    replay_id: UUID = REPLAY_ID,
    status: ReplayStatus = ReplayStatus.CREATED,
    declared_size_bytes: int = 1_000_000,
    source_object_key: str = f"source/{REPLAY_ID}/input",
) -> ReplayUploadRow:
    return ReplayUploadRow(
        id=replay_id,
        match_id="NA1_1234567890",
        platform="NA1",
        selected_puuid="selected-player-puuid",
        match_duration_ms=1_800_000,
        status=status.value,
        processing_stage=None,
        progress_percent=0,
        token_digest="digest",
        original_filename="owned recording.mp4",
        declared_content_type="video/mp4",
        declared_size_bytes=declared_size_bytes,
        game_time_zero_ms=48231,
        source_object_key=source_object_key,
        rights_statement_version="2026-08-01",
        rights_attested_at=NOW,
        upload_expires_at=NOW + timedelta(minutes=30),
        warning_codes=[],
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )


class ControllableReplayService:
    def __init__(self) -> None:
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
        self.status_result = _status_data()
        self.authorize_row = _upload_row()
        self.authorize_error: ApiError | None = None
        self.complete_calls = 0
        self.retry_calls = 0
        self.delete_calls = 0
        self.mark_uploaded_calls: list[dict[str, object]] = []
        self.artifact_content: ReplayArtifactContent | None = ReplayArtifactContent(
            artifact_id=ARTIFACT_ID,
            media_type="video/mp4",
            size_bytes=10,
            object_key=f"derived/{REPLAY_ID}/normalized",
        )
        self.artifacts = [
            ReplayArtifactResponse(
                artifact_id=ARTIFACT_ID,
                replay_id=REPLAY_ID,
                kind=ReplayArtifactKind.VERIFICATION_FRAME,
                game_time_ms=0,
                video_time_ms=48231,
                media_type="image/jpeg",
                width=1280,
                height=720,
                size_bytes=2048,
                access=ReplayArtifactAccess(
                    mode="bearer",
                    url=(
                        f"/api/v1/replays/{REPLAY_ID}/artifacts/{ARTIFACT_ID}/content"
                    ),
                    expires_at=NOW + timedelta(minutes=5),
                ),
            )
        ]

    async def create(
        self, request: ReplayCreateRequest, *, now: datetime | None = None
    ) -> ReplayCreateData:
        del request, now
        return self.create_result

    async def authorize(self, replay_id: UUID, token: str) -> ReplayUploadRow:
        if self.authorize_error is not None:
            raise self.authorize_error
        if token != TOKEN or replay_id != REPLAY_ID:
            raise ApiError(
                status_code=404,
                code="REPLAY_NOT_FOUND",
                message="The requested replay was not found.",
                retryable=False,
            )
        return self.authorize_row

    async def mark_local_uploaded(
        self,
        replay_id: UUID,
        token: str,
        *,
        actual_size_bytes: int,
        now: datetime | None = None,
    ) -> ReplayStatusData:
        del now
        await self.authorize(replay_id, token)
        self.mark_uploaded_calls.append(
            {"replay_id": replay_id, "actual_size_bytes": actual_size_bytes}
        )
        self.authorize_row.status = ReplayStatus.UPLOADED.value
        return _status_data(status=ReplayStatus.UPLOADED)

    async def complete(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData:
        del now
        await self.authorize(replay_id, token)
        self.complete_calls += 1
        return self.status_result

    async def get_status(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData:
        del now
        await self.authorize(replay_id, token)
        return self.status_result

    async def list_artifacts(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> list[ReplayArtifactResponse]:
        del now
        await self.authorize(replay_id, token)
        return list(self.artifacts)

    async def get_ready_artifact_content(
        self, replay_id: UUID, artifact_id: UUID, token: str
    ) -> ReplayArtifactContent:
        await self.authorize(replay_id, token)
        if self.artifact_content is None or artifact_id != ARTIFACT_ID:
            raise ApiError(
                status_code=404,
                code="REPLAY_NOT_FOUND",
                message="The requested replay was not found.",
                retryable=False,
            )
        if ReplayStatus(self.authorize_row.status) != ReplayStatus.READY:
            raise ApiError(
                status_code=404,
                code="REPLAY_NOT_FOUND",
                message="The requested replay was not found.",
                retryable=False,
            )
        return self.artifact_content

    async def retry(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData:
        del now
        await self.authorize(replay_id, token)
        self.retry_calls += 1
        return _status_data(status=ReplayStatus.QUEUED)

    async def request_delete(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData:
        del now
        await self.authorize(replay_id, token)
        self.delete_calls += 1
        return _status_data(status=ReplayStatus.DELETING)


@pytest.fixture
def replay_service() -> ControllableReplayService:
    return ControllableReplayService()


@pytest.fixture
def replay_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+asyncpg://user:pass@db:5432/lol_ai_coach",
        backend_cors_origins="http://localhost:3000",
        riot_api_key="RGAPI-test",
        replay_enabled=True,
        replay_token_secret="x" * 32,
        replay_storage_backend="local",
        replay_local_root=tmp_path,
        replay_max_bytes=1024,
    )


@pytest.fixture
def replay_storage(tmp_path: Path) -> LocalReplayStorage:
    return LocalReplayStorage(tmp_path)


@pytest.fixture
def replay_client(
    replay_settings: Settings,
    replay_service: ControllableReplayService,
    replay_storage: LocalReplayStorage,
) -> Generator[TestClient, None, None]:
    services = AppServices(
        player_service=object(),  # type: ignore[arg-type]
        match_service=object(),  # type: ignore[arg-type]
        replay_service=replay_service,  # type: ignore[arg-type]
        closers=(),
    )
    with TestClient(
        create_app(
            settings=replay_settings,
            database=FakeDatabase(),
            services=services,
            replay_storage=replay_storage,
        )
    ) as client:
        yield client


def _auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_create_replay_returns_access_token_and_matching_request_id(
    replay_client: TestClient,
) -> None:
    response = replay_client.post("/api/v1/replays", json=VALID_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["access_token"] == "returned-once"
    assert body["replay_id"] == str(REPLAY_ID)
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_wrong_bearer_token_returns_replay_not_found(
    replay_client: TestClient,
) -> None:
    response = replay_client.get(
        f"/api/v1/replays/{REPLAY_ID}", headers=_auth("wrong")
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPLAY_NOT_FOUND"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer " + ("t" * 513)},
    ],
)
def test_illegal_bearer_formats_return_replay_not_found(
    replay_client: TestClient, headers: dict[str, str]
) -> None:
    response = replay_client.get(f"/api/v1/replays/{REPLAY_ID}", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "REPLAY_NOT_FOUND"


def test_complete_is_idempotent_at_api_layer(
    replay_client: TestClient, replay_service: ControllableReplayService
) -> None:
    first = replay_client.post(
        f"/api/v1/replays/{REPLAY_ID}/complete", headers=_auth()
    )
    second = replay_client.post(
        f"/api/v1/replays/{REPLAY_ID}/complete", headers=_auth()
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "queued"
    assert second.json()["status"] == "queued"
    assert first.json()["request_id"] == first.headers["X-Request-ID"]
    assert replay_service.complete_calls == 2


def test_local_put_streams_and_marks_uploaded(
    replay_client: TestClient,
    replay_service: ControllableReplayService,
    replay_storage: LocalReplayStorage,
) -> None:
    payload = b"0123456789"

    response = replay_client.put(
        f"/api/v1/replays/{REPLAY_ID}/content",
        content=payload,
        headers={**_auth(), "Content-Length": str(len(payload))},
    )

    assert response.status_code == 204
    assert replay_service.mark_uploaded_calls == [
        {"replay_id": REPLAY_ID, "actual_size_bytes": 10}
    ]
    assert (
        replay_storage.resolve_key(f"source/{REPLAY_ID}/input").read_bytes() == payload
    )


def test_local_put_rejects_oversize_content_length(replay_client: TestClient) -> None:
    response = replay_client.put(
        f"/api/v1/replays/{REPLAY_ID}/content",
        content=b"x" * 2048,
        headers=_auth(),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REPLAY_TOO_LARGE"


@pytest.mark.asyncio
async def test_artifact_range_returns_206_and_416(
    replay_client: TestClient,
    replay_service: ControllableReplayService,
    replay_storage: LocalReplayStorage,
) -> None:
    payload = b"0123456789"
    key = f"derived/{REPLAY_ID}/normalized"

    async def chunks() -> AsyncIterator[bytes]:
        yield payload

    await replay_storage.write_stream(key, chunks(), max_bytes=len(payload))
    replay_service.authorize_row.status = ReplayStatus.READY.value
    replay_service.artifact_content = ReplayArtifactContent(
        artifact_id=ARTIFACT_ID,
        media_type="video/mp4",
        size_bytes=len(payload),
        object_key=key,
    )

    ok = replay_client.get(
        f"/api/v1/replays/{REPLAY_ID}/artifacts/{ARTIFACT_ID}/content",
        headers={**_auth(), "Range": "bytes=2-5"},
    )
    assert ok.status_code == 206
    assert ok.content == b"2345"
    assert ok.headers["Accept-Ranges"] == "bytes"
    assert ok.headers["Content-Range"] == "bytes 2-5/10"
    assert ok.headers["Content-Type"] == "video/mp4"
    assert str(ARTIFACT_ID) in ok.headers["Content-Disposition"]
    assert "owned recording" not in ok.headers["Content-Disposition"]
    assert "recording.mp4" not in ok.headers.get("Content-Disposition", "")

    multi = replay_client.get(
        f"/api/v1/replays/{REPLAY_ID}/artifacts/{ARTIFACT_ID}/content",
        headers={**_auth(), "Range": "bytes=0-1,4-5"},
    )
    assert multi.status_code == 416

    oob = replay_client.get(
        f"/api/v1/replays/{REPLAY_ID}/artifacts/{ARTIFACT_ID}/content",
        headers={**_auth(), "Range": "bytes=8-20"},
    )
    assert oob.status_code == 416


def test_retry_and_delete_idempotent(
    replay_client: TestClient, replay_service: ControllableReplayService
) -> None:
    retry = replay_client.post(f"/api/v1/replays/{REPLAY_ID}/retry", headers=_auth())
    assert retry.status_code == 200
    assert retry.json()["status"] == "queued"
    assert replay_service.retry_calls == 1

    first_delete = replay_client.delete(
        f"/api/v1/replays/{REPLAY_ID}", headers=_auth()
    )
    second_delete = replay_client.delete(
        f"/api/v1/replays/{REPLAY_ID}", headers=_auth()
    )
    assert first_delete.status_code == 200
    assert second_delete.status_code == 200
    assert first_delete.json()["status"] == "deleting"
    assert second_delete.json()["status"] == "deleting"
    assert replay_service.delete_calls == 2


def test_status_and_artifacts_manifest(
    replay_client: TestClient, replay_service: ControllableReplayService
) -> None:
    replay_service.status_result = _status_data(status=ReplayStatus.READY)
    status = replay_client.get(f"/api/v1/replays/{REPLAY_ID}", headers=_auth())
    assert status.status_code == 200
    assert status.json()["status"] == "ready"
    assert status.json()["request_id"] == status.headers["X-Request-ID"]

    artifacts = replay_client.get(
        f"/api/v1/replays/{REPLAY_ID}/artifacts", headers=_auth()
    )
    assert artifacts.status_code == 200
    body = artifacts.json()
    assert body["artifacts"][0]["artifact_id"] == str(ARTIFACT_ID)
    assert body["request_id"] == artifacts.headers["X-Request-ID"]
    assert "object_key" not in artifacts.text
    assert "token_digest" not in artifacts.text


def test_replay_cors_allows_put_delete_auth_and_range_headers(
    replay_client: TestClient,
) -> None:
    response = replay_client.options(
        f"/api/v1/replays/{REPLAY_ID}",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type,range",
        },
    )

    assert response.status_code == 200
    allow_methods = response.headers["access-control-allow-methods"]
    assert "PUT" in allow_methods
    assert "DELETE" in allow_methods
    allow_headers = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allow_headers
    assert "range" in allow_headers
    exposed = response.headers.get("access-control-expose-headers", "")
    # expose headers appear on actual responses; preflight may omit them
    get_response = replay_client.get(
        f"/api/v1/replays/{REPLAY_ID}",
        headers={**_auth(), "Origin": "http://localhost:3000"},
    )
    exposed = get_response.headers["access-control-expose-headers"]
    assert "Accept-Ranges" in exposed
    assert "Content-Range" in exposed
    assert "X-Request-ID" in exposed
