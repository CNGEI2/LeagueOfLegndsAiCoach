"""Lightweight in-memory metrics registry, no third-party dependency required.

Exposes Prometheus-style counters/histograms and can render them in the
Prometheus text exposition format so a scraper (or a human) can hit
`GET /internal/metrics` without adding `prometheus_client` to the backend.

Caveat: state lives in the process that recorded it. The replay API and the
replay worker run in separate containers in `docker-compose.yml`, so worker
metrics (processing duration/failures/retries/cleanup lag) are only visible
via this endpoint when the worker and API share a process, e.g. in tests. In
multi-container production, ship the worker's registry via a push gateway or
a shared multiprocess backend; that wiring is out of scope here.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable

_DEFAULT_DURATION_BUCKETS: tuple[float, ...] = (
    1.0,
    5.0,
    15.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
    1800.0,
    3600.0,
    7200.0,
)
_DEFAULT_LAG_BUCKETS: tuple[float, ...] = (
    0.0,
    1.0,
    5.0,
    30.0,
    60.0,
    300.0,
    900.0,
    3600.0,
    21600.0,
    86400.0,
)


def _label_key(labels: dict[str, str]) -> str:
    return "\x1f".join(f"{key}={value}" for key, value in sorted(labels.items()))


class Counter:
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description
        self._lock = threading.Lock()
        self._values: dict[str, float] = {}
        self._labels: dict[str, dict[str, str]] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = _label_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount
            self._labels[key] = dict(labels)

    def value(self, **labels: str) -> float:
        key = _label_key(labels)
        with self._lock:
            return self._values.get(key, 0.0)

    def samples(self) -> list[tuple[dict[str, str], float]]:
        with self._lock:
            return [(dict(self._labels[key]), value) for key, value in self._values.items()]


class Gauge:
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description
        self._lock = threading.Lock()
        self._values: dict[str, float] = {}
        self._labels: dict[str, dict[str, str]] = {}

    def set(self, value: float, **labels: str) -> None:
        key = _label_key(labels)
        with self._lock:
            self._values[key] = value
            self._labels[key] = dict(labels)

    def value(self, **labels: str) -> float | None:
        key = _label_key(labels)
        with self._lock:
            return self._values.get(key)

    def samples(self) -> list[tuple[dict[str, str], float]]:
        with self._lock:
            return [(dict(self._labels[key]), value) for key, value in self._values.items()]


class Histogram:
    def __init__(
        self,
        name: str,
        description: str = "",
        buckets: Iterable[float] = _DEFAULT_DURATION_BUCKETS,
    ) -> None:
        self.name = name
        self.description = description
        self._buckets = tuple(sorted(buckets))
        self._lock = threading.Lock()
        self._bucket_counts: dict[str, list[int]] = {}
        self._sums: dict[str, float] = {}
        self._counts: dict[str, int] = {}
        self._labels: dict[str, dict[str, str]] = {}

    def observe(self, value: float, **labels: str) -> None:
        key = _label_key(labels)
        with self._lock:
            counts = self._bucket_counts.setdefault(key, [0] * len(self._buckets))
            for index, bound in enumerate(self._buckets):
                if value <= bound:
                    counts[index] += 1
            self._sums[key] = self._sums.get(key, 0.0) + value
            self._counts[key] = self._counts.get(key, 0) + 1
            self._labels[key] = dict(labels)

    def count(self, **labels: str) -> int:
        key = _label_key(labels)
        with self._lock:
            return self._counts.get(key, 0)

    def sum(self, **labels: str) -> float:
        key = _label_key(labels)
        with self._lock:
            return self._sums.get(key, 0.0)

    def samples(self) -> list[tuple[dict[str, str], list[int], float, int]]:
        with self._lock:
            return [
                (
                    dict(self._labels[key]),
                    list(self._bucket_counts[key]),
                    self._sums[key],
                    self._counts[key],
                )
                for key in self._counts
            ]


class MetricsRegistry:
    """Process-local registry for the Replay R1 production-hardening metrics."""

    def __init__(self) -> None:
        self.replay_processing_duration_seconds = Histogram(
            "replay_processing_duration_seconds",
            "Time spent processing a replay job end to end, labeled by stage.",
        )
        self.replay_processing_failures_total = Counter(
            "replay_processing_failures_total",
            "Replay processing failures, labeled by error_code.",
        )
        self.replay_job_retries_total = Counter(
            "replay_job_retries_total",
            "Replay job retries scheduled after a retryable failure.",
        )
        self.replay_cleanup_lag_seconds = Histogram(
            "replay_cleanup_lag_seconds",
            "Seconds between a cleanup deadline (delete_after) and when cleanup actually ran.",
            buckets=_DEFAULT_LAG_BUCKETS,
        )
        self.replay_rate_limit_rejections_total = Counter(
            "replay_rate_limit_rejections_total",
            "Replay gateway requests rejected for exceeding a rate limit, labeled by limit.",
        )

    def render_prometheus_text(self) -> str:
        lines: list[str] = []
        for counter in (
            self.replay_processing_failures_total,
            self.replay_job_retries_total,
            self.replay_rate_limit_rejections_total,
        ):
            lines.append(f"# HELP {counter.name} {counter.description}")
            lines.append(f"# TYPE {counter.name} counter")
            for labels, value in counter.samples():
                lines.append(f"{counter.name}{_format_labels(labels)} {value}")
        for histogram in (
            self.replay_processing_duration_seconds,
            self.replay_cleanup_lag_seconds,
        ):
            lines.append(f"# HELP {histogram.name} {histogram.description}")
            lines.append(f"# TYPE {histogram.name} histogram")
            for labels, bucket_counts, total_sum, total_count in histogram.samples():
                for bound, bucket_count in zip(histogram._buckets, bucket_counts, strict=True):
                    bucket_labels = {**labels, "le": _format_bound(bound)}
                    bucket_name = f"{histogram.name}_bucket{_format_labels(bucket_labels)}"
                    lines.append(f"{bucket_name} {bucket_count}")
                inf_labels = {**labels, "le": "+Inf"}
                lines.append(f"{histogram.name}_bucket{_format_labels(inf_labels)} {total_count}")
                lines.append(f"{histogram.name}_sum{_format_labels(labels)} {total_sum}")
                lines.append(f"{histogram.name}_count{_format_labels(labels)} {total_count}")
        return "\n".join(lines) + "\n"


def _format_bound(bound: float) -> str:
    if bound == int(bound):
        return str(int(bound))
    return str(bound)


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    body = ",".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
    return "{" + body + "}"


metrics = MetricsRegistry()

__all__ = ["Counter", "Gauge", "Histogram", "MetricsRegistry", "metrics"]
