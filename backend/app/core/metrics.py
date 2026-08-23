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

import hashlib
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
_DETECTION_DURATION_BUCKETS: tuple[float, ...] = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    30.0,
)
_TIMELINE_FETCH_DURATION_BUCKETS: tuple[float, ...] = _DETECTION_DURATION_BUCKETS

JOINT_EVIDENCE_API_OUTCOMES = frozenset({"ready", "error"})
JOINT_EVIDENCE_API_ERROR_CODES = frozenset(
    {
        "none",
        "NOT_FOUND",
        "MATCH_NOT_FOUND",
        "PLAYER_NOT_IN_MATCH",
        "MATCH_EVIDENCE_UNSUPPORTED_MODE",
        "MATCH_TIMELINE_NOT_FOUND",
        "REPLAY_NOT_FOUND",
        "REPLAY_EVIDENCE_NOT_READY",
        "RIOT_AUTH_FAILED",
        "RIOT_RATE_LIMITED",
        "RIOT_INVALID_RESPONSE",
        "RIOT_UNAVAILABLE",
        "VALIDATION_ERROR",
    }
)


def is_joint_evidence_prepare_request(*, method: str, path: str) -> bool:
    if method != "POST":
        return False
    parts = path.strip("/").split("/")
    return (
        len(parts) == 5
        and parts[0] == "api"
        and parts[1] == "v1"
        and parts[2] == "matches"
        and parts[4] == "evidence"
        and bool(parts[3])
    )


def record_joint_evidence_api_request(
    registry: MetricsRegistry,
    *,
    outcome: str,
    error_code: str,
) -> None:
    safe_outcome = outcome if outcome in JOINT_EVIDENCE_API_OUTCOMES else "error"
    if safe_outcome == "ready":
        safe_code = "none"
    elif error_code in JOINT_EVIDENCE_API_ERROR_CODES and error_code != "none":
        safe_code = error_code
    else:
        safe_code = "NOT_FOUND"
    registry.joint_evidence_api_requests_total.inc(outcome=safe_outcome, error_code=safe_code)


ANALYSIS_API_OUTCOMES = frozenset({"ready", "error"})
ANALYSIS_API_ERROR_CODES = frozenset(
    {
        "none",
        "NOT_FOUND",
        "VALIDATION_ERROR",
        "MATCH_ANALYSIS_UNSUPPORTED_MODE",
        "PLAYER_NOT_IN_MATCH",
        "MATCH_NOT_FOUND",
        "RIOT_AUTH_FAILED",
        "RIOT_RATE_LIMITED",
        "RIOT_INVALID_RESPONSE",
        "RIOT_UNAVAILABLE",
        "INTERNAL_SERVER_ERROR",
        "HTTP_ERROR",
    }
)
ANALYSIS_CACHE_STATUSES = frozenset({"hit", "miss"})
ANALYSIS_RESULT_STATUSES = frozenset({"completed", "partial"})
ANALYSIS_COVERAGE_BUCKETS = frozenset({"lt_60", "60_79", "80_99", "100"})
ANALYSIS_STAGES = frozenset({"compute", "persist", "total"})
ANALYSIS_IDEMPOTENCY_RESULTS = frozenset({"created", "reused"})
ANALYSIS_UNAVAILABLE_REASONS = frozenset(
    {
        "missing_match_value",
        "invalid_duration",
        "division_by_zero",
        "timeline_unavailable",
        "role_unavailable",
        "opponent_unavailable",
        "opponent_ambiguous",
        "insufficient_team_values",
    }
)


def hashed_analysis_puuid(puuid: str) -> str:
    return hashlib.sha256(puuid.encode("utf-8")).hexdigest()[:12]


def is_analysis_request(*, method: str, path: str) -> bool:
    if method not in {"GET", "POST"}:
        return False
    parts = path.strip("/").split("/")
    if parts == ["api", "v1", "analyses"]:
        return method == "POST"
    return (
        method == "GET"
        and len(parts) == 4
        and parts[:3] == ["api", "v1", "analyses"]
        and bool(parts[3])
    )


def record_analysis_api_request(
    registry: MetricsRegistry,
    *,
    outcome: str,
    error_code: str,
) -> None:
    safe_outcome = outcome if outcome in ANALYSIS_API_OUTCOMES else "error"
    if safe_outcome == "ready":
        safe_code = "none"
    elif error_code in ANALYSIS_API_ERROR_CODES and error_code != "none":
        safe_code = error_code
    else:
        safe_code = "NOT_FOUND"
    registry.analysis_api_requests_total.inc(outcome=safe_outcome, error_code=safe_code)


def record_analysis_duration(registry: MetricsRegistry, *, stage: str, seconds: float) -> None:
    safe_stage = stage if stage in ANALYSIS_STAGES else "total"
    registry.analysis_duration_seconds.observe(seconds, stage=safe_stage)


def record_analysis_cache(registry: MetricsRegistry, *, status: str) -> None:
    safe_status = status if status in ANALYSIS_CACHE_STATUSES else "miss"
    registry.analysis_cache_total.inc(status=safe_status)


def record_analysis_result(registry: MetricsRegistry, *, status: str) -> None:
    safe_status = status if status in ANALYSIS_RESULT_STATUSES else "partial"
    registry.analysis_results_total.inc(status=safe_status)


def record_analysis_coverage(registry: MetricsRegistry, *, bucket: str) -> None:
    safe_bucket = bucket if bucket in ANALYSIS_COVERAGE_BUCKETS else "lt_60"
    registry.analysis_coverage_total.inc(bucket=safe_bucket)


def analysis_coverage_bucket(coverage: float) -> str:
    if coverage < 0.60:
        return "lt_60"
    if coverage < 0.80:
        return "60_79"
    if coverage < 1.0:
        return "80_99"
    return "100"


def record_analysis_unavailable(registry: MetricsRegistry, *, reason: str) -> None:
    if reason not in ANALYSIS_UNAVAILABLE_REASONS:
        return
    registry.analysis_unavailable_signals_total.inc(reason=reason)


def record_analysis_finding_count(registry: MetricsRegistry, *, count: int) -> None:
    registry.analysis_finding_count.inc(amount=float(count))


def record_analysis_goal_count(registry: MetricsRegistry, *, count: int) -> None:
    registry.analysis_goal_count.inc(amount=float(count))


def record_analysis_idempotency(registry: MetricsRegistry, *, result: str) -> None:
    safe_result = result if result in ANALYSIS_IDEMPOTENCY_RESULTS else "reused"
    registry.analysis_idempotency_total.inc(result=safe_result)


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
    """Process-local registry for replay and Riot platform-detection metrics."""

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
        self.riot_platform_detection_requests_total = Counter(
            "riot_platform_detection_requests_total",
            "Platform detection requests, labeled by closed-set outcome.",
        )
        self.riot_platform_detection_duration_seconds = Histogram(
            "riot_platform_detection_duration_seconds",
            "Platform detection latency in seconds, labeled by closed-set outcome.",
            buckets=_DETECTION_DURATION_BUCKETS,
        )
        self.riot_platform_detection_cache_total = Counter(
            "riot_platform_detection_cache_total",
            "Platform detection cache lookups, labeled by closed-set status.",
        )
        self.riot_platform_detection_probes_total = Counter(
            "riot_platform_detection_probes_total",
            "Summoner platform probes, labeled by closed-set result.",
        )
        self.riot_platform_confirmation_total = Counter(
            "riot_platform_confirmation_total",
            "Platform confirmation attempts, labeled by closed-set outcome.",
        )
        self.joint_evidence_timeline_requests_total = Counter(
            "joint_evidence_timeline_requests_total",
            "Timeline evidence requests, labeled by closed-set outcome.",
        )
        self.joint_evidence_timeline_cache_total = Counter(
            "joint_evidence_timeline_cache_total",
            "Timeline cache lookups, labeled by closed-set status.",
        )
        self.joint_evidence_timeline_fetch_duration_seconds = Histogram(
            "joint_evidence_timeline_fetch_duration_seconds",
            "Timeline upstream fetch latency in seconds, labeled by closed-set outcome.",
            buckets=_TIMELINE_FETCH_DURATION_BUCKETS,
        )
        self.joint_evidence_timeline_events_total = Counter(
            "joint_evidence_timeline_events_total",
            "Normalized Timeline events, labeled by closed-set event_type and result.",
        )
        self.joint_evidence_singleflight_total = Counter(
            "joint_evidence_singleflight_total",
            "Timeline single-flight participation, labeled by closed-set result.",
        )
        self.joint_evidence_windows_total = Counter(
            "joint_evidence_windows_total",
            "Planned evidence windows, labeled by closed-set result.",
        )
        self.joint_evidence_window_truncations_total = Counter(
            "joint_evidence_window_truncations_total",
            "Evidence window truncation outcomes, labeled by closed-set result.",
        )
        self.joint_evidence_replay_coverage_total = Counter(
            "joint_evidence_replay_coverage_total",
            "Evidence window replay coverage, labeled by closed-set coverage.",
        )
        self.joint_evidence_api_requests_total = Counter(
            "joint_evidence_api_requests_total",
            "Joint evidence API requests, labeled by closed-set outcome and error_code.",
        )
        self.analysis_api_requests_total = Counter(
            "analysis_api_requests_total",
            "Analysis API requests, labeled by closed-set outcome and error_code.",
        )
        self.analysis_duration_seconds = Histogram(
            "analysis_duration_seconds",
            "Analysis latency in seconds, labeled by closed-set stage.",
        )
        self.analysis_cache_total = Counter(
            "analysis_cache_total",
            "Analysis cache lookups, labeled by closed-set status.",
        )
        self.analysis_results_total = Counter(
            "analysis_results_total",
            "Analysis results, labeled by closed-set status.",
        )
        self.analysis_coverage_total = Counter(
            "analysis_coverage_total",
            "Analysis coverage, labeled by closed-set bucket.",
        )
        self.analysis_unavailable_signals_total = Counter(
            "analysis_unavailable_signals_total",
            "Unavailable analysis signals, labeled by closed-set reason.",
        )
        self.analysis_finding_count = Counter(
            "analysis_finding_count",
            "Findings emitted by deterministic analysis.",
        )
        self.analysis_goal_count = Counter(
            "analysis_goal_count",
            "Goals emitted by deterministic analysis.",
        )
        self.analysis_idempotency_total = Counter(
            "analysis_idempotency_total",
            "Analysis persistence outcomes, labeled by closed-set result.",
        )

    def render_prometheus_text(self) -> str:
        lines: list[str] = []
        for counter in (
            self.replay_processing_failures_total,
            self.replay_job_retries_total,
            self.replay_rate_limit_rejections_total,
            self.riot_platform_detection_requests_total,
            self.riot_platform_detection_cache_total,
            self.riot_platform_detection_probes_total,
            self.riot_platform_confirmation_total,
            self.joint_evidence_timeline_requests_total,
            self.joint_evidence_timeline_cache_total,
            self.joint_evidence_timeline_events_total,
            self.joint_evidence_singleflight_total,
            self.joint_evidence_windows_total,
            self.joint_evidence_window_truncations_total,
            self.joint_evidence_replay_coverage_total,
            self.joint_evidence_api_requests_total,
            self.analysis_api_requests_total,
            self.analysis_cache_total,
            self.analysis_results_total,
            self.analysis_coverage_total,
            self.analysis_unavailable_signals_total,
            self.analysis_finding_count,
            self.analysis_goal_count,
            self.analysis_idempotency_total,
        ):
            lines.append(f"# HELP {counter.name} {counter.description}")
            lines.append(f"# TYPE {counter.name} counter")
            for labels, value in counter.samples():
                lines.append(f"{counter.name}{_format_labels(labels)} {value}")
        for histogram in (
            self.replay_processing_duration_seconds,
            self.replay_cleanup_lag_seconds,
            self.riot_platform_detection_duration_seconds,
            self.joint_evidence_timeline_fetch_duration_seconds,
            self.analysis_duration_seconds,
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

__all__ = [
    "ANALYSIS_API_ERROR_CODES",
    "ANALYSIS_API_OUTCOMES",
    "ANALYSIS_CACHE_STATUSES",
    "ANALYSIS_COVERAGE_BUCKETS",
    "ANALYSIS_IDEMPOTENCY_RESULTS",
    "ANALYSIS_RESULT_STATUSES",
    "ANALYSIS_STAGES",
    "ANALYSIS_UNAVAILABLE_REASONS",
    "Counter",
    "Gauge",
    "Histogram",
    "JOINT_EVIDENCE_API_ERROR_CODES",
    "JOINT_EVIDENCE_API_OUTCOMES",
    "MetricsRegistry",
    "analysis_coverage_bucket",
    "hashed_analysis_puuid",
    "is_analysis_request",
    "is_joint_evidence_prepare_request",
    "metrics",
    "record_analysis_api_request",
    "record_analysis_cache",
    "record_analysis_coverage",
    "record_analysis_duration",
    "record_analysis_finding_count",
    "record_analysis_goal_count",
    "record_analysis_idempotency",
    "record_analysis_result",
    "record_analysis_unavailable",
    "record_joint_evidence_api_request",
]
