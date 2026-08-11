from typing import Any

from app.services.timelines.domain import TIMELINE_SCHEMA_VERSION, TimelineSnapshot
from app.services.timelines.normalizer import TimelineNormalizationResult, TimelineNormalizer

__all__ = [
    "TIMELINE_SCHEMA_VERSION",
    "TimelineLoadResult",
    "TimelineNormalizationResult",
    "TimelineNormalizer",
    "TimelineResolver",
    "TimelineService",
    "TimelineSnapshot",
]


def __getattr__(name: str) -> Any:
    if name in {"TimelineLoadResult", "TimelineResolver", "TimelineService"}:
        from app.services.timelines.service import (
            TimelineLoadResult,
            TimelineResolver,
            TimelineService,
        )

        exports = {
            "TimelineLoadResult": TimelineLoadResult,
            "TimelineResolver": TimelineResolver,
            "TimelineService": TimelineService,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
