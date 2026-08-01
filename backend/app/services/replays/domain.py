from dataclasses import dataclass
from enum import StrEnum


class ReplayStatus(StrEnum):
    CREATED = "created"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROBING = "probing"
    TRANSCODING = "transcoding"
    EXTRACTING = "extracting"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"
    DELETING = "deleting"
    DELETED = "deleted"


class ReplayJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY_SCHEDULED = "retry_scheduled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReplayJobKind(StrEnum):
    PROCESS = "process"
    DELETE_SOURCE = "delete_source"
    DELETE_ALL = "delete_all"


class ReplayArtifactKind(StrEnum):
    ANCHOR_FRAME = "anchor_frame"
    VERIFICATION_FRAME = "verification_frame"


@dataclass(frozen=True)
class ReplayCoverage:
    start_ms: int
    end_ms: int
    partial: bool

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.end_ms < 0:
            raise ValueError("coverage times must be non-negative")
        if self.start_ms > self.end_ms:
            raise ValueError("coverage start_ms must be <= end_ms")


def game_to_video_time(game_time_ms: int, game_time_zero_ms: int) -> int:
    if game_time_ms < 0 or game_time_zero_ms < 0:
        raise ValueError("time values must be non-negative")
    return game_time_zero_ms + game_time_ms


def video_to_game_time(video_time_ms: int, game_time_zero_ms: int) -> int:
    if video_time_ms < 0 or game_time_zero_ms < 0:
        raise ValueError("time values must be non-negative")
    return video_time_ms - game_time_zero_ms


def calculate_coverage(
    video_duration_ms: int,
    game_time_zero_ms: int,
    match_duration_ms: int,
) -> ReplayCoverage:
    if video_duration_ms < 0 or game_time_zero_ms < 0 or match_duration_ms < 0:
        raise ValueError("time values must be non-negative")
    if game_time_zero_ms >= video_duration_ms:
        raise ValueError("game_time_zero_ms must be within the video duration")

    available_end_ms = video_duration_ms - game_time_zero_ms
    end_ms = min(available_end_ms, match_duration_ms)
    return ReplayCoverage(
        start_ms=0,
        end_ms=end_ms,
        partial=available_end_ms < match_duration_ms,
    )
