from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.replays import (
    ReplayArtifactAccess,
    ReplayArtifactResponse,
    ReplayCreateRequest,
    ReplayCreateResponse,
    ReplayRetentionInfo,
    ReplayStatusResponse,
    ReplayUploadInfo,
)
from app.services.replays.domain import ReplayArtifactKind, ReplayStatus

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


def _valid_create_request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "match_id": "NA1_1234567890",
        "platform": "NA1",
        "puuid": "selected-player-puuid",
        "original_filename": "recording.mp4",
        "declared_size_bytes": 123456789,
        "declared_content_type": "video/mp4",
        "game_time_zero_ms": 48231,
        "rights_attested": True,
        "rights_statement_version": "2026-08-01",
    }
    payload.update(overrides)
    return payload


def test_replay_create_request_accepts_required_public_fields() -> None:
    request = ReplayCreateRequest.model_validate(_valid_create_request())
    assert request.match_id == "NA1_1234567890"
    assert request.rights_attested is True
    assert request.rights_statement_version == "2026-08-01"


@pytest.mark.parametrize(
    "forbidden_field",
    ["token_digest", "selected_puuid", "source_object_key", "object_key"],
)
def test_replay_create_request_rejects_forbidden_fields(forbidden_field: str) -> None:
    payload = _valid_create_request(**{forbidden_field: "secret"})
    with pytest.raises(ValidationError):
        ReplayCreateRequest.model_validate(payload)


def test_replay_create_response_accepts_required_public_fields() -> None:
    response = ReplayCreateResponse(
        replay_id=uuid4(),
        access_token="returned-once",
        status=ReplayStatus.CREATED,
        upload=ReplayUploadInfo(
            method="PUT",
            url="/api/v1/replays/x/content",
            headers={},
            expires_at=NOW,
        ),
        retention=ReplayRetentionInfo(
            source_hours_after_processing=24,
            derived_days_after_ready=7,
        ),
        request_id="abc123",
    )
    dumped = response.model_dump()
    assert dumped["access_token"] == "returned-once"
    assert "token_digest" not in dumped
    assert "original_filename" not in dumped
    assert "object_key" not in dumped
    assert "selected_puuid" not in dumped


@pytest.mark.parametrize(
    "forbidden_field",
    ["token_digest", "selected_puuid", "original_filename", "object_key", "source_object_key"],
)
def test_replay_create_response_rejects_forbidden_fields(forbidden_field: str) -> None:
    payload = {
        "replay_id": str(uuid4()),
        "access_token": "token",
        "status": "created",
        "upload": {
            "method": "PUT",
            "url": "/api/v1/replays/x/content",
            "headers": {},
            "expires_at": NOW.isoformat(),
        },
        "retention": {
            "source_hours_after_processing": 24,
            "derived_days_after_ready": 7,
        },
        "request_id": "abc123",
        forbidden_field: "secret",
    }
    with pytest.raises(ValidationError):
        ReplayCreateResponse.model_validate(payload)


def test_replay_status_response_accepts_required_public_fields() -> None:
    response = ReplayStatusResponse(
        replay_id=uuid4(),
        status=ReplayStatus.READY,
        processing_stage=None,
        progress_percent=100,
        normalized_duration_ms=1_800_000,
        width=1280,
        height=720,
        available_game_time_start_ms=0,
        available_game_time_end_ms=1_800_000,
        warning_codes=["partial_coverage"],
        error_code=None,
        error_retryable=None,
        source_delete_after=NOW,
        derived_delete_after=NOW,
        request_id="abc123",
    )
    dumped = response.model_dump()
    assert set(dumped) == {
        "replay_id",
        "status",
        "processing_stage",
        "progress_percent",
        "normalized_duration_ms",
        "width",
        "height",
        "available_game_time_start_ms",
        "available_game_time_end_ms",
        "warning_codes",
        "error_code",
        "error_retryable",
        "source_delete_after",
        "derived_delete_after",
        "request_id",
    }


@pytest.mark.parametrize(
    "forbidden_field",
    ["token_digest", "selected_puuid", "original_filename", "object_key", "source_object_key"],
)
def test_replay_status_response_rejects_forbidden_fields(forbidden_field: str) -> None:
    payload = {
        "replay_id": str(uuid4()),
        "status": "ready",
        "processing_stage": None,
        "progress_percent": 100,
        "normalized_duration_ms": None,
        "width": None,
        "height": None,
        "available_game_time_start_ms": None,
        "available_game_time_end_ms": None,
        "warning_codes": [],
        "error_code": None,
        "error_retryable": None,
        "source_delete_after": None,
        "derived_delete_after": None,
        "request_id": "abc123",
        forbidden_field: "secret",
    }
    with pytest.raises(ValidationError):
        ReplayStatusResponse.model_validate(payload)


def test_replay_artifact_response_accepts_required_public_fields() -> None:
    response = ReplayArtifactResponse(
        artifact_id=uuid4(),
        replay_id=uuid4(),
        kind=ReplayArtifactKind.ANCHOR_FRAME,
        game_time_ms=0,
        video_time_ms=1000,
        media_type="image/jpeg",
        width=1280,
        height=720,
        size_bytes=12_345,
        access=ReplayArtifactAccess(
            mode="bearer",
            url="/api/v1/replays/x/artifacts/y/content",
            expires_at=NOW,
        ),
    )
    dumped = response.model_dump()
    assert "object_key" not in dumped
    assert "sha256" not in dumped
    assert dumped["access"]["mode"] == "bearer"


@pytest.mark.parametrize(
    "forbidden_field",
    ["object_key", "sha256", "token_digest", "selected_puuid", "original_filename"],
)
def test_replay_artifact_response_rejects_forbidden_fields(forbidden_field: str) -> None:
    payload = {
        "artifact_id": str(uuid4()),
        "replay_id": str(uuid4()),
        "kind": "anchor_frame",
        "game_time_ms": 0,
        "video_time_ms": 1000,
        "media_type": "image/jpeg",
        "width": 1280,
        "height": 720,
        "size_bytes": 12_345,
        "access": {
            "mode": "bearer",
            "url": "/api/v1/replays/x/artifacts/y/content",
            "expires_at": NOW.isoformat(),
        },
        forbidden_field: "secret",
    }
    with pytest.raises(ValidationError):
        ReplayArtifactResponse.model_validate(payload)
