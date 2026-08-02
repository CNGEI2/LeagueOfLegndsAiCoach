from app.repositories.matches import MatchCacheConflict, MatchRepository, SqlMatchRepository
from app.repositories.platform_detections import (
    DetectionStatus,
    PlatformDetectionRecord,
    PlatformDetectionRepository,
    SqlPlatformDetectionRepository,
)
from app.repositories.players import PlayerRepository, SqlPlayerRepository
from app.repositories.recent_matches import RecentMatchRepository, SqlRecentMatchRepository
from app.repositories.replays import (
    ReplayArtifactConflict,
    ReplayArtifactRepository,
    ReplayJobRepository,
    ReplayRepository,
    ReplayStateConflict,
    SqlReplayArtifactRepository,
    SqlReplayJobRepository,
    SqlReplayRepository,
)

__all__ = [
    "DetectionStatus",
    "MatchCacheConflict",
    "MatchRepository",
    "PlatformDetectionRecord",
    "PlatformDetectionRepository",
    "PlayerRepository",
    "RecentMatchRepository",
    "ReplayArtifactConflict",
    "ReplayArtifactRepository",
    "ReplayJobRepository",
    "ReplayRepository",
    "ReplayStateConflict",
    "SqlMatchRepository",
    "SqlPlatformDetectionRepository",
    "SqlPlayerRepository",
    "SqlRecentMatchRepository",
    "SqlReplayArtifactRepository",
    "SqlReplayJobRepository",
    "SqlReplayRepository",
]
