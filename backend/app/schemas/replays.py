from datetime import datetime
from typing import Literal
from uuid import UUID

from app.core.routing import Platform
from app.schemas.domain import DomainModel
from app.services.replays.domain import ReplayArtifactKind, ReplayStatus


class ReplayCreateRequest(DomainModel):
    match_id: str
    platform: Platform
    puuid: str
    original_filename: str
    declared_size_bytes: int
    declared_content_type: str
    game_time_zero_ms: int
    rights_attested: bool
    rights_statement_version: str


class ReplayUploadInfo(DomainModel):
    method: str
    url: str
    headers: dict[str, str]
    expires_at: datetime


class ReplayRetentionInfo(DomainModel):
    source_hours_after_processing: int
    derived_days_after_ready: int


class ReplayCreateData(DomainModel):
    replay_id: UUID
    access_token: str
    status: ReplayStatus
    upload: ReplayUploadInfo
    retention: ReplayRetentionInfo


class ReplayCreateResponse(ReplayCreateData):
    request_id: str


class ReplayStatusData(DomainModel):
    replay_id: UUID
    status: ReplayStatus
    processing_stage: str | None
    progress_percent: int
    normalized_duration_ms: int | None
    width: int | None
    height: int | None
    available_game_time_start_ms: int | None
    available_game_time_end_ms: int | None
    warning_codes: tuple[str, ...]
    error_code: str | None
    error_retryable: bool | None
    source_delete_after: datetime | None
    derived_delete_after: datetime | None


class ReplayStatusResponse(ReplayStatusData):
    request_id: str


class ReplayArtifactAccess(DomainModel):
    mode: Literal["bearer", "presigned"]
    url: str
    expires_at: datetime


class ReplayArtifactResponse(DomainModel):
    artifact_id: UUID
    replay_id: UUID
    kind: ReplayArtifactKind
    game_time_ms: int
    video_time_ms: int
    media_type: str
    width: int | None
    height: int | None
    size_bytes: int
    access: ReplayArtifactAccess


class ReplayArtifactsResponse(DomainModel):
    artifacts: tuple[ReplayArtifactResponse, ...]
    request_id: str
