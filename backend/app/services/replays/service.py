from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Protocol
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.errors import ApiError, replay_not_found, replay_too_large
from app.models.replay import ReplayUploadRow
from app.repositories.matches import MatchRepository
from app.repositories.replays import (
    ReplayArtifactRepository,
    ReplayJobRepository,
    ReplayRepository,
)
from app.schemas.replays import (
    ReplayArtifactAccess,
    ReplayArtifactResponse,
    ReplayCreateData,
    ReplayCreateRequest,
    ReplayRetentionInfo,
    ReplayStatusData,
    ReplayUploadInfo,
)
from app.services.replays.domain import ReplayArtifactKind, ReplayJobKind, ReplayStatus
from app.services.replays.security import issue_replay_token, verify_replay_token
from app.services.replays.storage.base import (
    ReplayObjectNotFound,
    ReplayStorage,
)


@dataclass(frozen=True)
class ReplayArtifactContent:
    artifact_id: UUID
    media_type: str
    size_bytes: int
    object_key: str

RIGHTS_STATEMENT_VERSION = "2026-08-01"
_ACCEPTED_EXTENSIONS = frozenset({".mp4", ".mkv", ".mov", ".webm"})
_CONTENT_TYPES_BY_EXTENSION: dict[str, frozenset[str]] = {
    ".mp4": frozenset({"video/mp4", "application/octet-stream"}),
    ".mkv": frozenset({"video/x-matroska", "video/mkv", "application/octet-stream"}),
    ".mov": frozenset({"video/quicktime", "application/octet-stream"}),
    ".webm": frozenset({"video/webm", "application/octet-stream"}),
}
_COMPLETE_IDEMPOTENT_STATUSES = frozenset(
    {
        ReplayStatus.QUEUED,
        ReplayStatus.PROBING,
        ReplayStatus.TRANSCODING,
        ReplayStatus.EXTRACTING,
        ReplayStatus.READY,
    }
)
_DELETE_IDEMPOTENT_STATUSES = frozenset({ReplayStatus.DELETING, ReplayStatus.DELETED})
_ARTIFACT_ACCESS_TTL = timedelta(minutes=5)


class ReplayServiceProtocol(Protocol):
    async def create(
        self, request: ReplayCreateRequest, *, now: datetime | None = None
    ) -> ReplayCreateData: ...

    async def authorize(self, replay_id: UUID, token: str) -> ReplayUploadRow: ...

    async def mark_local_uploaded(
        self,
        replay_id: UUID,
        token: str,
        *,
        actual_size_bytes: int,
        now: datetime | None = None,
    ) -> ReplayStatusData: ...

    async def complete(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData: ...

    async def get_status(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData: ...

    async def list_artifacts(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> list[ReplayArtifactResponse]: ...

    async def get_ready_artifact_content(
        self, replay_id: UUID, artifact_id: UUID, token: str
    ) -> ReplayArtifactContent: ...

    async def retry(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData: ...

    async def request_delete(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData: ...


class DisabledReplayService:
    async def create(
        self, request: ReplayCreateRequest, *, now: datetime | None = None
    ) -> ReplayCreateData:
        raise _replay_disabled()

    async def authorize(self, replay_id: UUID, token: str) -> ReplayUploadRow:
        raise _replay_disabled()

    async def mark_local_uploaded(
        self,
        replay_id: UUID,
        token: str,
        *,
        actual_size_bytes: int,
        now: datetime | None = None,
    ) -> ReplayStatusData:
        raise _replay_disabled()

    async def complete(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData:
        raise _replay_disabled()

    async def get_status(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData:
        raise _replay_disabled()

    async def list_artifacts(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> list[ReplayArtifactResponse]:
        raise _replay_disabled()

    async def get_ready_artifact_content(
        self, replay_id: UUID, artifact_id: UUID, token: str
    ) -> ReplayArtifactContent:
        raise _replay_disabled()

    async def retry(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData:
        raise _replay_disabled()

    async def request_delete(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData:
        raise _replay_disabled()


class ReplayService:
    def __init__(
        self,
        *,
        settings: Settings,
        match_repository: MatchRepository,
        replay_repository: ReplayRepository,
        job_repository: ReplayJobRepository,
        artifact_repository: ReplayArtifactRepository,
        storage: ReplayStorage,
    ) -> None:
        self._settings = settings
        self._match_repository = match_repository
        self._replay_repository = replay_repository
        self._job_repository = job_repository
        self._artifact_repository = artifact_repository
        self._storage = storage

    async def create(
        self, request: ReplayCreateRequest, *, now: datetime | None = None
    ) -> ReplayCreateData:
        if not self._settings.replay_enabled:
            raise _replay_disabled()

        clock = now or datetime.now(UTC)
        self._validate_create_request(request)

        snapshot = await self._match_repository.get_for_replay_binding(
            platform=request.platform,
            match_id=request.match_id,
        )
        if snapshot is None:
            raise ApiError(
                status_code=404,
                code="REPLAY_MATCH_NOT_FOUND",
                message="The match was not found for replay binding.",
                retryable=False,
            )
        if not any(participant.puuid == request.puuid for participant in snapshot.participants):
            raise ApiError(
                status_code=404,
                code="REPLAY_PLAYER_NOT_IN_MATCH",
                message="The selected player did not participate in this match.",
                retryable=False,
            )

        token_secret = self._settings.replay_token_secret.get_secret_value().encode("utf-8")
        access_token, token_digest = issue_replay_token(token_secret)
        replay_id = uuid4()
        upload_expires_at = clock + timedelta(seconds=self._settings.replay_upload_expiry_seconds)
        source_object_key = f"source/{replay_id}/input"
        upload_url = f"/api/v1/replays/{replay_id}/content"

        upload_target = await self._storage.create_upload_target(
            source_object_key,
            expires_at=upload_expires_at,
            upload_url=upload_url,
            headers={},
        )

        row = ReplayUploadRow(
            id=replay_id,
            match_id=request.match_id,
            platform=request.platform.value,
            selected_puuid=request.puuid,
            match_duration_ms=snapshot.duration_seconds * 1000,
            status=ReplayStatus.CREATED.value,
            processing_stage=None,
            progress_percent=0,
            token_digest=token_digest,
            original_filename=request.original_filename,
            declared_content_type=request.declared_content_type,
            declared_size_bytes=request.declared_size_bytes,
            game_time_zero_ms=request.game_time_zero_ms,
            source_object_key=source_object_key,
            rights_statement_version=request.rights_statement_version,
            rights_attested_at=clock,
            upload_expires_at=upload_expires_at,
            warning_codes=[],
            created_at=clock,
            updated_at=clock,
            version=1,
        )
        await self._replay_repository.create(row)

        return ReplayCreateData(
            replay_id=replay_id,
            access_token=access_token,
            status=ReplayStatus.CREATED,
            upload=ReplayUploadInfo(
                method=upload_target.method,
                url=upload_target.url,
                headers=dict(upload_target.headers),
                expires_at=upload_target.expires_at,
            ),
            retention=ReplayRetentionInfo(
                source_hours_after_processing=self._settings.replay_source_retention_hours,
                derived_days_after_ready=self._settings.replay_derived_retention_days,
            ),
        )

    async def authorize(self, replay_id: UUID, token: str) -> ReplayUploadRow:
        return await self._authorize(replay_id, token)

    async def mark_local_uploaded(
        self,
        replay_id: UUID,
        token: str,
        *,
        actual_size_bytes: int,
        now: datetime | None = None,
    ) -> ReplayStatusData:
        clock = now or datetime.now(UTC)
        row = await self._authorize(replay_id, token)
        if ReplayStatus(row.status) == ReplayStatus.UPLOADED:
            return _status_data(row)
        if ReplayStatus(row.status) != ReplayStatus.CREATED:
            raise replay_not_found()
        if row.upload_expires_at <= clock:
            raise ApiError(
                status_code=410,
                code="REPLAY_UPLOAD_EXPIRED",
                message="The replay upload window has expired.",
                retryable=False,
            )
        if actual_size_bytes > self._settings.replay_max_bytes:
            raise replay_too_large()
        if actual_size_bytes > row.declared_size_bytes:
            raise ApiError(
                status_code=422,
                code="REPLAY_UPLOAD_INVALID",
                message="The uploaded replay size exceeds the declared size.",
                retryable=False,
            )
        updated = await self._replay_repository.transition(
            replay_id=row.id,
            expected_statuses={ReplayStatus.CREATED},
            expected_version=row.version,
            status=ReplayStatus.UPLOADED,
            values={"actual_size_bytes": actual_size_bytes, "updated_at": clock},
        )
        return _status_data(updated)

    async def complete(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData:
        clock = now or datetime.now(UTC)
        row = await self._authorize(replay_id, token)
        status = ReplayStatus(row.status)

        if status in _COMPLETE_IDEMPOTENT_STATUSES:
            return _status_data(row)

        if status not in {ReplayStatus.CREATED, ReplayStatus.UPLOADED}:
            raise replay_not_found()
        if row.upload_expires_at <= clock:
            raise ApiError(
                status_code=410,
                code="REPLAY_UPLOAD_EXPIRED",
                message="The replay upload window has expired.",
                retryable=False,
            )
        if not row.source_object_key:
            raise ApiError(
                status_code=422,
                code="REPLAY_UPLOAD_INVALID",
                message="The replay upload is incomplete.",
                retryable=False,
            )

        try:
            stored = await self._storage.stat(row.source_object_key)
        except ReplayObjectNotFound as error:
            raise ApiError(
                status_code=422,
                code="REPLAY_UPLOAD_INVALID",
                message="The uploaded replay object was not found.",
                retryable=False,
            ) from error
        except Exception as error:
            raise ApiError(
                status_code=503,
                code="REPLAY_STORAGE_UNAVAILABLE",
                message="Replay storage is temporarily unavailable.",
                retryable=True,
            ) from error

        if stored.size_bytes > self._settings.replay_max_bytes:
            raise replay_too_large()
        if stored.size_bytes > row.declared_size_bytes:
            raise ApiError(
                status_code=422,
                code="REPLAY_UPLOAD_INVALID",
                message="The uploaded replay size exceeds the declared size.",
                retryable=False,
            )

        if status == ReplayStatus.CREATED:
            row = await self._replay_repository.transition(
                replay_id=row.id,
                expected_statuses={ReplayStatus.CREATED},
                expected_version=row.version,
                status=ReplayStatus.UPLOADED,
                values={
                    "actual_size_bytes": stored.size_bytes,
                    "source_sha256": stored.sha256,
                    "updated_at": clock,
                },
            )

        await self._job_repository.enqueue(
            replay_id=row.id,
            kind=ReplayJobKind.PROCESS,
            available_at=clock,
        )
        updated = await self._replay_repository.transition(
            replay_id=row.id,
            expected_statuses={ReplayStatus.UPLOADED},
            expected_version=row.version,
            status=ReplayStatus.QUEUED,
            values={
                "actual_size_bytes": stored.size_bytes,
                "source_sha256": stored.sha256,
                "updated_at": clock,
            },
        )
        return _status_data(updated)

    async def get_status(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData:
        del now
        row = await self._authorize(replay_id, token)
        return _status_data(row)

    async def list_artifacts(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> list[ReplayArtifactResponse]:
        clock = now or datetime.now(UTC)
        row = await self._authorize(replay_id, token)
        status = ReplayStatus(row.status)
        if status in {ReplayStatus.DELETING, ReplayStatus.DELETED, ReplayStatus.EXPIRED}:
            raise replay_not_found()

        expires_at = clock + _ARTIFACT_ACCESS_TTL
        artifacts = await self._artifact_repository.list_for_replay(replay_id)
        return [
            ReplayArtifactResponse(
                artifact_id=artifact.id,
                replay_id=artifact.replay_id,
                kind=ReplayArtifactKind(artifact.kind),
                game_time_ms=artifact.game_time_ms,
                video_time_ms=artifact.video_time_ms,
                media_type=artifact.media_type,
                width=artifact.width,
                height=artifact.height,
                size_bytes=artifact.size_bytes,
                access=ReplayArtifactAccess(
                    mode="bearer",
                    url=(
                        f"/api/v1/replays/{artifact.replay_id}/artifacts/{artifact.id}/content"
                    ),
                    expires_at=expires_at,
                ),
            )
            for artifact in artifacts
        ]

    async def get_ready_artifact_content(
        self, replay_id: UUID, artifact_id: UUID, token: str
    ) -> ReplayArtifactContent:
        row = await self._authorize(replay_id, token)
        if ReplayStatus(row.status) != ReplayStatus.READY:
            raise replay_not_found()
        for artifact in await self._artifact_repository.list_for_replay(replay_id):
            if artifact.id == artifact_id:
                return ReplayArtifactContent(
                    artifact_id=artifact.id,
                    media_type=artifact.media_type,
                    size_bytes=artifact.size_bytes,
                    object_key=artifact.object_key,
                )
        raise replay_not_found()

    async def retry(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData:
        clock = now or datetime.now(UTC)
        row = await self._authorize(replay_id, token)
        if (
            ReplayStatus(row.status) != ReplayStatus.FAILED
            or row.error_retryable is not True
            or row.source_delete_after is None
            or row.source_delete_after <= clock
            or not row.source_object_key
        ):
            raise ApiError(
                status_code=409,
                code="REPLAY_RETRY_NOT_ALLOWED",
                message="This replay cannot be retried.",
                retryable=False,
            )

        try:
            await self._storage.stat(row.source_object_key)
        except ReplayObjectNotFound as error:
            raise ApiError(
                status_code=409,
                code="REPLAY_RETRY_NOT_ALLOWED",
                message="This replay cannot be retried.",
                retryable=False,
            ) from error
        except Exception as error:
            raise ApiError(
                status_code=503,
                code="REPLAY_STORAGE_UNAVAILABLE",
                message="Replay storage is temporarily unavailable.",
                retryable=True,
            ) from error

        await self._job_repository.enqueue(
            replay_id=row.id,
            kind=ReplayJobKind.PROCESS,
            available_at=clock,
        )
        updated = await self._replay_repository.transition(
            replay_id=row.id,
            expected_statuses={ReplayStatus.FAILED},
            expected_version=row.version,
            status=ReplayStatus.QUEUED,
            values={
                "error_code": None,
                "error_retryable": None,
                "processing_stage": None,
                "progress_percent": 0,
                "updated_at": clock,
            },
        )
        return _status_data(updated)

    async def request_delete(
        self, replay_id: UUID, token: str, *, now: datetime | None = None
    ) -> ReplayStatusData:
        clock = now or datetime.now(UTC)
        row = await self._authorize(replay_id, token)
        status = ReplayStatus(row.status)
        if status in _DELETE_IDEMPOTENT_STATUSES:
            return _status_data(row)

        updated = await self._replay_repository.transition(
            replay_id=row.id,
            expected_statuses={
                ReplayStatus.CREATED,
                ReplayStatus.UPLOADED,
                ReplayStatus.QUEUED,
                ReplayStatus.PROBING,
                ReplayStatus.TRANSCODING,
                ReplayStatus.EXTRACTING,
                ReplayStatus.READY,
                ReplayStatus.FAILED,
                ReplayStatus.EXPIRED,
            },
            expected_version=row.version,
            status=ReplayStatus.DELETING,
            values={"updated_at": clock},
        )
        await self._job_repository.enqueue(
            replay_id=row.id,
            kind=ReplayJobKind.DELETE_ALL,
            available_at=clock,
        )
        return _status_data(updated)

    async def _authorize(self, replay_id: UUID, token: str) -> ReplayUploadRow:
        if not token:
            raise replay_not_found()
        row = await self._replay_repository.get(replay_id)
        if row is None or row.token_digest is None:
            raise replay_not_found()
        token_secret = self._settings.replay_token_secret.get_secret_value().encode("utf-8")
        if not verify_replay_token(token_secret, token, row.token_digest):
            raise replay_not_found()
        return row

    def _validate_create_request(self, request: ReplayCreateRequest) -> None:
        if (
            not request.rights_attested
            or request.rights_statement_version != RIGHTS_STATEMENT_VERSION
        ):
            raise ApiError(
                status_code=422,
                code="REPLAY_RIGHTS_ATTESTATION_REQUIRED",
                message="A valid rights attestation is required to upload a replay.",
                retryable=False,
            )
        if request.declared_size_bytes > self._settings.replay_max_bytes:
            raise replay_too_large()
        if request.declared_size_bytes <= 0 or request.game_time_zero_ms < 0:
            raise ApiError(
                status_code=422,
                code="REPLAY_UPLOAD_INVALID",
                message="The replay upload declaration is invalid.",
                retryable=False,
            )
        extension = PurePosixPath(request.original_filename).suffix.lower()
        allowed_types = _CONTENT_TYPES_BY_EXTENSION.get(extension)
        if extension not in _ACCEPTED_EXTENSIONS or allowed_types is None:
            raise ApiError(
                status_code=422,
                code="REPLAY_UPLOAD_INVALID",
                message="The replay filename or content type is not supported.",
                retryable=False,
            )
        if request.declared_content_type not in allowed_types:
            raise ApiError(
                status_code=422,
                code="REPLAY_UPLOAD_INVALID",
                message="The replay filename or content type is not supported.",
                retryable=False,
            )


def _status_data(row: ReplayUploadRow) -> ReplayStatusData:
    warning_codes = tuple(str(code) for code in (row.warning_codes or []))
    return ReplayStatusData(
        replay_id=row.id,
        status=ReplayStatus(row.status),
        processing_stage=row.processing_stage,
        progress_percent=row.progress_percent,
        normalized_duration_ms=row.normalized_duration_ms,
        width=row.width,
        height=row.height,
        available_game_time_start_ms=row.available_game_time_start_ms,
        available_game_time_end_ms=row.available_game_time_end_ms,
        warning_codes=warning_codes,
        error_code=row.error_code,
        error_retryable=row.error_retryable,
        source_delete_after=row.source_delete_after,
        derived_delete_after=row.derived_delete_after,
    )


def _replay_disabled() -> ApiError:
    return ApiError(
        status_code=503,
        code="REPLAY_DISABLED",
        message="Replay uploads are disabled.",
        retryable=False,
    )


