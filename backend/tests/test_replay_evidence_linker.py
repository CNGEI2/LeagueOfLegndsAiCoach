from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.core.errors import ApiError
from app.core.routing import Platform
from app.models.replay import ReplayArtifactRow, ReplayUploadRow
from app.services.evidence.domain import (
    EvidenceArtifactReference,
    LinkedEvidenceWindow,
    PlannedEvidenceWindow,
)
from app.services.evidence.replay import ReplayEvidenceLinker
from app.services.replays.domain import ReplayArtifactKind, ReplayStatus
from app.services.replays.service import replay_evidence_not_ready

NOW = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)
REPLAY_ID = uuid4()
TOKEN = "valid-token"
PLATFORM = Platform.NA1
MATCH_ID = "NA1_fixture"
PUUID = "selected-player-puuid"
GAME_ZERO = 1_000


def _window(
    *,
    ordinal: int = 0,
    start_ms: int,
    end_ms: int,
    categories: tuple[str, ...] = ("combat_context",),
    trigger_fact_ids: tuple[str, ...] = ("timeline:NA1:NA1_fixture:v1:frame:1:event:0",),
) -> PlannedEvidenceWindow:
    return PlannedEvidenceWindow(
        window_id=f"evidence-window:NA1:NA1_fixture:v1:{ordinal}",
        start_ms=start_ms,
        end_ms=end_ms,
        categories=categories,  # type: ignore[arg-type]
        trigger_fact_ids=trigger_fact_ids,
    )


def _row(**overrides: object) -> ReplayUploadRow:
    values: dict[str, object] = {
        "id": REPLAY_ID,
        "match_id": MATCH_ID,
        "platform": PLATFORM.value,
        "selected_puuid": PUUID,
        "match_duration_ms": 1_800_000,
        "status": ReplayStatus.READY.value,
        "processing_stage": None,
        "progress_percent": 100,
        "token_digest": "digest",
        "original_filename": "clip.mp4",
        "declared_content_type": "video/mp4",
        "declared_size_bytes": 1000,
        "actual_container": "mp4",
        "actual_size_bytes": 1000,
        "source_sha256": "a" * 64,
        "source_duration_ms": 1_900_000,
        "normalized_duration_ms": 1_900_000,
        "width": 1280,
        "height": 720,
        "frame_rate_numerator": 30,
        "frame_rate_denominator": 1,
        "game_time_zero_ms": GAME_ZERO,
        "available_game_time_start_ms": 0,
        "available_game_time_end_ms": 1_800_000,
        "source_object_key": "source-key",
        "normalized_object_key": "normalized-key",
        "rights_statement_version": "2026-08-01",
        "rights_attested_at": NOW,
        "upload_expires_at": NOW,
        "source_delete_after": None,
        "derived_delete_after": None,
        "warning_codes": [],
        "error_code": None,
        "error_retryable": None,
        "created_at": NOW,
        "updated_at": NOW,
        "processing_started_at": NOW,
        "processing_finished_at": NOW,
        "deleted_at": None,
        "version": 1,
    }
    values.update(overrides)
    return ReplayUploadRow(**values)  # type: ignore[arg-type]


def _artifact(
    *,
    artifact_id: UUID | None = None,
    kind: ReplayArtifactKind = ReplayArtifactKind.ANCHOR_FRAME,
    game_time_ms: int,
    video_time_ms: int | None = None,
) -> ReplayArtifactRow:
    return ReplayArtifactRow(
        id=artifact_id or uuid4(),
        replay_id=REPLAY_ID,
        kind=kind.value,
        game_time_ms=game_time_ms,
        video_time_ms=GAME_ZERO + game_time_ms if video_time_ms is None else video_time_ms,
        object_key=f"artifacts/{uuid4()}.jpg",
        sha256="b" * 64,
        media_type="image/jpeg",
        size_bytes=100,
        width=1280,
        height=720,
        duration_ms=None,
        created_at=NOW,
        delete_after=None,
    )


@dataclass
class FakeReplayService:
    row: ReplayUploadRow | None = None
    error: ApiError | None = None
    authorize_calls: int = 0
    mutate_after_first: ReplayUploadRow | ApiError | None = None

    async def authorize(self, replay_id: UUID, token: str) -> ReplayUploadRow:
        self.authorize_calls += 1
        if not token:
            raise ApiError(
                status_code=404,
                code="REPLAY_NOT_FOUND",
                message="The requested replay was not found.",
                retryable=False,
            )
        if self.error is not None:
            raise self.error
        if self.row is None:
            raise ApiError(
                status_code=404,
                code="REPLAY_NOT_FOUND",
                message="The requested replay was not found.",
                retryable=False,
            )
        if self.authorize_calls == 1:
            return self.row
        if isinstance(self.mutate_after_first, ApiError):
            raise self.mutate_after_first
        if isinstance(self.mutate_after_first, ReplayUploadRow):
            return self.mutate_after_first
        return self.row


@dataclass
class FakeArtifactRepository:
    rows: list[ReplayArtifactRow]
    list_calls: int = 0

    async def list_for_replay(self, replay_id: UUID) -> list[ReplayArtifactRow]:
        self.list_calls += 1
        return list(self.rows)


def _linker(
    *,
    service: FakeReplayService | None = None,
    artifacts: list[ReplayArtifactRow] | None = None,
) -> tuple[ReplayEvidenceLinker, FakeReplayService, FakeArtifactRepository]:
    replay_service = service or FakeReplayService(row=_row())
    repository = FakeArtifactRepository(rows=artifacts or [])
    linker = ReplayEvidenceLinker(
        replay_service=replay_service,
        artifact_repository=repository,
    )
    return linker, replay_service, repository


@pytest.mark.asyncio
async def test_without_replay_request_all_windows_are_unavailable() -> None:
    linker, service, repository = _linker()
    windows = (_window(start_ms=10_000, end_ms=20_000),)
    linked = await linker.link(
        windows=windows,
        replay_id=None,
        token=None,
        platform=PLATFORM,
        match_id=MATCH_ID,
        selected_puuid=PUUID,
    )
    assert len(linked) == 1
    assert linked[0].coverage == "unavailable"
    assert linked[0].covered_game_start_ms is None
    assert linked[0].covered_game_end_ms is None
    assert linked[0].video_start_ms is None
    assert linked[0].video_end_ms is None
    assert linked[0].artifacts == ()
    assert service.authorize_calls == 0
    assert repository.list_calls == 0


@pytest.mark.asyncio
async def test_full_partial_and_boundary_coverage_with_sorted_safe_artifacts() -> None:
    inside_early = _artifact(
        kind=ReplayArtifactKind.VERIFICATION_FRAME,
        game_time_ms=10_000,
    )
    boundary_start = _artifact(
        artifact_id=uuid4(),
        kind=ReplayArtifactKind.VERIFICATION_FRAME,
        game_time_ms=5_000,
    )
    boundary_end = _artifact(game_time_ms=15_000)
    outside = _artifact(game_time_ms=15_001)
    same_time_anchor = _artifact(
        artifact_id=UUID("00000000-0000-0000-0000-000000000099"),
        kind=ReplayArtifactKind.ANCHOR_FRAME,
        game_time_ms=10_000,
        video_time_ms=GAME_ZERO + 10_000,
    )
    linker, service, repository = _linker(
        service=FakeReplayService(
            row=_row(available_game_time_start_ms=5_000, available_game_time_end_ms=15_000)
        ),
        artifacts=[outside, boundary_end, same_time_anchor, inside_early, boundary_start],
    )
    windows = (
        _window(ordinal=0, start_ms=5_000, end_ms=15_000),
        _window(ordinal=1, start_ms=0, end_ms=20_000),
        _window(ordinal=2, start_ms=20_000, end_ms=30_000),
    )
    linked = await linker.link(
        windows=windows,
        replay_id=REPLAY_ID,
        token=TOKEN,
        platform=PLATFORM,
        match_id=MATCH_ID,
        selected_puuid=PUUID,
    )
    assert linked[0].coverage == "full"
    assert linked[0].covered_game_start_ms == 5_000
    assert linked[0].covered_game_end_ms == 15_000
    assert linked[0].video_start_ms == GAME_ZERO + 5_000
    assert linked[0].video_end_ms == GAME_ZERO + 15_000
    assert [ref.game_time_ms for ref in linked[0].artifacts] == [5_000, 10_000, 10_000, 15_000]
    assert linked[0].artifacts[1].kind == ReplayArtifactKind.ANCHOR_FRAME
    assert linked[0].artifacts[2].kind == ReplayArtifactKind.VERIFICATION_FRAME
    assert all(isinstance(ref, EvidenceArtifactReference) for ref in linked[0].artifacts)
    assert all(
        not hasattr(ref, "object_key") and not hasattr(ref, "sha256") for ref in linked[0].artifacts
    )
    assert linked[1].coverage == "partial"
    assert linked[1].covered_game_start_ms == 5_000
    assert linked[1].covered_game_end_ms == 15_000
    assert linked[2].coverage == "unavailable"
    assert linked[2].artifacts == ()
    assert service.authorize_calls == 2
    assert repository.list_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"platform": Platform.EUW1.value},
        {"match_id": "NA1_other"},
        {"selected_puuid": "other-puuid"},
        {"available_game_time_start_ms": None, "available_game_time_end_ms": None},
        {"available_game_time_start_ms": 100, "available_game_time_end_ms": 50},
        {"normalized_duration_ms": None},
        {"normalized_duration_ms": 0},
        {"normalized_duration_ms": -1},
        {"match_duration_ms": 0},
        {"match_duration_ms": -1},
        {"game_time_zero_ms": 1_900_000},
        {"game_time_zero_ms": 1_900_001},
        {
            "available_game_time_start_ms": 0,
            "available_game_time_end_ms": 1_800_001,
        },
        {
            "normalized_duration_ms": 1_000_000,
            "game_time_zero_ms": 1_000,
            "available_game_time_start_ms": 0,
            "available_game_time_end_ms": 999_001,
        },
    ],
)
async def test_binding_and_invalid_coverage_map_to_replay_not_found(overrides: dict) -> None:
    linker, _, repository = _linker(service=FakeReplayService(row=_row(**overrides)))
    with pytest.raises(ApiError) as raised:
        await linker.link(
            windows=(_window(start_ms=0, end_ms=10_000),),
            replay_id=REPLAY_ID,
            token=TOKEN,
            platform=PLATFORM,
            match_id=MATCH_ID,
            selected_puuid=PUUID,
        )
    assert raised.value.code == "REPLAY_NOT_FOUND"
    assert raised.value.status_code == 404
    assert repository.list_calls == 0
    assert PUUID not in raised.value.message
    assert "1_800_001" not in raised.value.message
    assert "999_001" not in raised.value.message
    assert "normalized" not in raised.value.message.lower()


@pytest.mark.asyncio
async def test_missing_token_and_authorize_failure_are_replay_not_found() -> None:
    linker, service, repository = _linker(
        service=FakeReplayService(
            error=ApiError(
                status_code=404,
                code="REPLAY_NOT_FOUND",
                message="The requested replay was not found.",
                retryable=False,
            )
        )
    )
    with pytest.raises(ApiError) as missing:
        await linker.link(
            windows=(_window(start_ms=0, end_ms=10_000),),
            replay_id=REPLAY_ID,
            token=None,
            platform=PLATFORM,
            match_id=MATCH_ID,
            selected_puuid=PUUID,
        )
    assert missing.value.code == "REPLAY_NOT_FOUND"

    with pytest.raises(ApiError) as invalid:
        await linker.link(
            windows=(_window(start_ms=0, end_ms=10_000),),
            replay_id=REPLAY_ID,
            token="bad",
            platform=PLATFORM,
            match_id=MATCH_ID,
            selected_puuid=PUUID,
        )
    assert invalid.value.code == "REPLAY_NOT_FOUND"
    assert repository.list_calls == 0


@pytest.mark.asyncio
async def test_authorized_non_ready_replay_returns_evidence_not_ready() -> None:
    linker, _, repository = _linker(
        service=FakeReplayService(row=_row(status=ReplayStatus.EXTRACTING.value))
    )
    with pytest.raises(ApiError) as raised:
        await linker.link(
            windows=(_window(start_ms=0, end_ms=10_000),),
            replay_id=REPLAY_ID,
            token=TOKEN,
            platform=PLATFORM,
            match_id=MATCH_ID,
            selected_puuid=PUUID,
        )
    assert raised.value.code == "REPLAY_EVIDENCE_NOT_READY"
    assert raised.value.status_code == 409
    assert raised.value.retryable is True
    assert repository.list_calls == 0


@pytest.mark.asyncio
async def test_deletion_race_after_artifact_list_discards_references() -> None:
    artifact = _artifact(game_time_ms=10_000)
    service = FakeReplayService(
        row=_row(),
        mutate_after_first=ApiError(
            status_code=404,
            code="REPLAY_NOT_FOUND",
            message="The requested replay was not found.",
            retryable=False,
        ),
    )
    linker, service, repository = _linker(service=service, artifacts=[artifact])
    with pytest.raises(ApiError) as raised:
        await linker.link(
            windows=(_window(start_ms=0, end_ms=20_000),),
            replay_id=REPLAY_ID,
            token=TOKEN,
            platform=PLATFORM,
            match_id=MATCH_ID,
            selected_puuid=PUUID,
        )
    assert raised.value.code == "REPLAY_NOT_FOUND"
    assert service.authorize_calls == 2
    assert repository.list_calls == 1
    assert "EvidenceArtifactReference" not in repr(raised.value)
    assert str(artifact.id) not in str(raised.value)
    assert artifact.object_key not in str(raised.value)


@pytest.mark.asyncio
async def test_second_authorization_binding_change_discards_assembled_result() -> None:
    artifact = _artifact(game_time_ms=10_000)
    changed = _row(version=2, selected_puuid="changed-puuid")
    linker, service, repository = _linker(
        service=FakeReplayService(row=_row(), mutate_after_first=changed),
        artifacts=[artifact],
    )
    with pytest.raises(ApiError) as raised:
        await linker.link(
            windows=(_window(start_ms=0, end_ms=20_000),),
            replay_id=REPLAY_ID,
            token=TOKEN,
            platform=PLATFORM,
            match_id=MATCH_ID,
            selected_puuid=PUUID,
        )
    assert raised.value.code == "REPLAY_NOT_FOUND"
    assert service.authorize_calls == 2
    assert repository.list_calls == 1
    assert str(artifact.id) not in repr(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        {"normalized_duration_ms": 1_850_000},
        {"match_duration_ms": 1_700_000},
    ],
)
async def test_duration_field_change_without_version_bump_discards_result(
    mutate: dict[str, int],
) -> None:
    artifact = _artifact(game_time_ms=10_000)
    changed = _row(**mutate)
    assert changed.version == 1
    linker, service, repository = _linker(
        service=FakeReplayService(row=_row(), mutate_after_first=changed),
        artifacts=[artifact],
    )
    with pytest.raises(ApiError) as raised:
        await linker.link(
            windows=(_window(start_ms=0, end_ms=20_000),),
            replay_id=REPLAY_ID,
            token=TOKEN,
            platform=PLATFORM,
            match_id=MATCH_ID,
            selected_puuid=PUUID,
        )
    assert raised.value.code == "REPLAY_NOT_FOUND"
    assert service.authorize_calls == 2
    assert repository.list_calls == 1
    assert str(artifact.id) not in repr(raised.value)
    assert str(artifact.object_key) not in raised.value.message
    assert PUUID not in raised.value.message


def test_linked_window_contract_has_no_unsafe_fields() -> None:
    linked = LinkedEvidenceWindow(
        window=_window(start_ms=0, end_ms=10),
        coverage="unavailable",
        covered_game_start_ms=None,
        covered_game_end_ms=None,
        video_start_ms=None,
        video_end_ms=None,
        artifacts=(),
    )
    payload = linked.__dict__
    for banned in ("object_key", "sha256", "token", "puuid", "path", "url"):
        assert banned not in payload
    assert replay_evidence_not_ready().code == "REPLAY_EVIDENCE_NOT_READY"
