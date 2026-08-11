from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.errors import replay_not_found
from app.core.routing import Platform
from app.models.replay import ReplayArtifactRow, ReplayUploadRow
from app.repositories.replays import ReplayArtifactRepository
from app.services.evidence.domain import (
    EvidenceArtifactReference,
    LinkedEvidenceWindow,
    PlannedEvidenceWindow,
    ReplayCoverageStatus,
)
from app.services.replays.domain import ReplayArtifactKind, ReplayStatus, game_to_video_time
from app.services.replays.service import ReplayServiceProtocol, replay_evidence_not_ready


class _ArtifactLister(Protocol):
    async def list_for_replay(self, replay_id: UUID) -> list[ReplayArtifactRow]: ...


@dataclass(frozen=True)
class _ReplayBindingSnapshot:
    version: int
    status: str
    platform: str
    match_id: str
    selected_puuid: str | None
    match_duration_ms: int
    normalized_duration_ms: int | None
    available_game_time_start_ms: int | None
    available_game_time_end_ms: int | None
    game_time_zero_ms: int


class ReplayEvidenceLinker:
    def __init__(
        self,
        *,
        replay_service: ReplayServiceProtocol,
        artifact_repository: ReplayArtifactRepository | _ArtifactLister,
    ) -> None:
        self._replay_service = replay_service
        self._artifact_repository = artifact_repository

    async def link(
        self,
        *,
        windows: Sequence[PlannedEvidenceWindow],
        replay_id: UUID | None,
        token: str | None,
        platform: Platform,
        match_id: str,
        selected_puuid: str,
    ) -> tuple[LinkedEvidenceWindow, ...]:
        if replay_id is None:
            return tuple(_unavailable(window) for window in windows)

        if not token:
            raise replay_not_found()

        first = await self._replay_service.authorize(replay_id, token)
        first_snapshot = _validate_ready_binding(
            first,
            platform=platform,
            match_id=match_id,
            selected_puuid=selected_puuid,
        )
        coverage_start = first.available_game_time_start_ms
        coverage_end = first.available_game_time_end_ms
        assert coverage_start is not None and coverage_end is not None

        artifact_rows = await self._artifact_repository.list_for_replay(replay_id)

        second = await self._replay_service.authorize(replay_id, token)
        second_snapshot = _binding_snapshot(second)
        if second_snapshot != first_snapshot:
            raise replay_not_found()
        _validate_ready_binding(
            second,
            platform=platform,
            match_id=match_id,
            selected_puuid=selected_puuid,
        )

        linked: list[LinkedEvidenceWindow] = []
        for window in windows:
            linked.append(
                _link_window(
                    window,
                    coverage_start=coverage_start,
                    coverage_end=coverage_end,
                    game_time_zero_ms=second.game_time_zero_ms,
                    artifact_rows=artifact_rows,
                )
            )
        return tuple(linked)


def _validate_ready_binding(
    row: ReplayUploadRow,
    *,
    platform: Platform,
    match_id: str,
    selected_puuid: str,
) -> _ReplayBindingSnapshot:
    if row.platform != platform.value or row.match_id != match_id:
        raise replay_not_found()
    if row.selected_puuid != selected_puuid:
        raise replay_not_found()
    try:
        status = ReplayStatus(row.status)
    except ValueError as error:
        raise replay_not_found() from error
    if status != ReplayStatus.READY:
        raise replay_evidence_not_ready()

    normalized_duration_ms = row.normalized_duration_ms
    if normalized_duration_ms is None or normalized_duration_ms <= 0:
        raise replay_not_found()
    if row.match_duration_ms <= 0:
        raise replay_not_found()
    if row.game_time_zero_ms < 0 or row.game_time_zero_ms >= normalized_duration_ms:
        raise replay_not_found()

    start = row.available_game_time_start_ms
    end = row.available_game_time_end_ms
    if start is None or end is None or start < 0 or end < 0 or start > end:
        raise replay_not_found()
    if end > row.match_duration_ms:
        raise replay_not_found()
    try:
        video_start = game_to_video_time(start, row.game_time_zero_ms)
        video_end = game_to_video_time(end, row.game_time_zero_ms)
    except ValueError as error:
        raise replay_not_found() from error
    if video_start > normalized_duration_ms or video_end > normalized_duration_ms:
        raise replay_not_found()

    return _binding_snapshot(row)


def _binding_snapshot(row: ReplayUploadRow) -> _ReplayBindingSnapshot:
    return _ReplayBindingSnapshot(
        version=row.version,
        status=row.status,
        platform=row.platform,
        match_id=row.match_id,
        selected_puuid=row.selected_puuid,
        match_duration_ms=row.match_duration_ms,
        normalized_duration_ms=row.normalized_duration_ms,
        available_game_time_start_ms=row.available_game_time_start_ms,
        available_game_time_end_ms=row.available_game_time_end_ms,
        game_time_zero_ms=row.game_time_zero_ms,
    )


def _link_window(
    window: PlannedEvidenceWindow,
    *,
    coverage_start: int,
    coverage_end: int,
    game_time_zero_ms: int,
    artifact_rows: Sequence[ReplayArtifactRow],
) -> LinkedEvidenceWindow:
    covered_start = max(window.start_ms, coverage_start)
    covered_end = min(window.end_ms, coverage_end)
    if covered_start > covered_end:
        return _unavailable(window)

    coverage: ReplayCoverageStatus
    if covered_start == window.start_ms and covered_end == window.end_ms:
        coverage = "full"
    else:
        coverage = "partial"

    artifacts = tuple(
        sorted(
            (
                EvidenceArtifactReference(
                    artifact_id=row.id,
                    kind=ReplayArtifactKind(row.kind),
                    game_time_ms=row.game_time_ms,
                    video_time_ms=row.video_time_ms,
                )
                for row in artifact_rows
                if covered_start <= row.game_time_ms <= covered_end
            ),
            key=lambda ref: (
                ref.game_time_ms,
                ref.video_time_ms,
                ref.kind.value,
                str(ref.artifact_id),
            ),
        )
    )
    return LinkedEvidenceWindow(
        window=window,
        coverage=coverage,
        covered_game_start_ms=covered_start,
        covered_game_end_ms=covered_end,
        video_start_ms=game_to_video_time(covered_start, game_time_zero_ms),
        video_end_ms=game_to_video_time(covered_end, game_time_zero_ms),
        artifacts=artifacts,
    )


def _unavailable(window: PlannedEvidenceWindow) -> LinkedEvidenceWindow:
    return LinkedEvidenceWindow(
        window=window,
        coverage="unavailable",
        covered_game_start_ms=None,
        covered_game_end_ms=None,
        video_start_ms=None,
        video_end_ms=None,
        artifacts=(),
    )
