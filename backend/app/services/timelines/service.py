from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from app.core.errors import ApiError
from app.core.metrics import MetricsRegistry
from app.core.routing import Platform
from app.repositories.timelines import TimelineCacheRecord, TimelineRepository
from app.services.riot.dto import TimelineDto
from app.services.timelines.domain import (
    TIMELINE_SCHEMA_VERSION,
    ParticipantStateFact,
    TimelineSnapshot,
)
from app.services.timelines.normalizer import TimelineNormalizationResult, TimelineNormalizer

TimelineCacheResult = Literal["hit", "miss"]

RequestOutcome = Literal[
    "available",
    "not_found",
    "auth_failed",
    "rate_limited",
    "invalid_response",
    "unavailable",
    "internal_error",
]
CacheMetricStatus = Literal["hit", "miss", "not_found"]
FetchOutcome = Literal[
    "available",
    "not_found",
    "auth_failed",
    "rate_limited",
    "invalid_response",
    "unavailable",
]
SingleflightResult = Literal["leader", "waiter", "shared_success", "shared_failure"]


@dataclass(frozen=True)
class TimelineLoadResult:
    snapshot: TimelineSnapshot
    cache_status: TimelineCacheResult


class TimelineGateway(Protocol):
    async def get_match_timeline(self, *, platform: Platform, match_id: str) -> TimelineDto: ...


class TimelineResolver(Protocol):
    async def get_timeline(self, *, platform: Platform, match_id: str) -> TimelineLoadResult: ...


class TimelineService:
    REQUEST_OUTCOMES = frozenset(
        {
            "available",
            "not_found",
            "auth_failed",
            "rate_limited",
            "invalid_response",
            "unavailable",
            "internal_error",
        }
    )
    CACHE_STATUSES = frozenset({"hit", "miss", "not_found"})
    FETCH_OUTCOMES = frozenset(
        {
            "available",
            "not_found",
            "auth_failed",
            "rate_limited",
            "invalid_response",
            "unavailable",
        }
    )
    EVENT_TYPES = frozenset(
        {
            "champion_kill",
            "elite_monster_kill",
            "building_kill",
            "item_purchased",
            "item_sold",
            "item_destroyed",
            "item_undo",
            "participant_state",
            "unknown",
        }
    )
    EVENT_RESULTS = frozenset({"supported", "ignored"})
    SINGLEFLIGHT_RESULTS = frozenset({"leader", "waiter", "shared_success", "shared_failure"})

    def __init__(
        self,
        *,
        repository: TimelineRepository,
        gateway: TimelineGateway,
        normalizer: TimelineNormalizer,
        metrics: MetricsRegistry,
        timeline_cache_ttl_seconds: int,
        timeline_not_found_ttl_seconds: int,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._normalizer = normalizer
        self._metrics = metrics
        self._positive_ttl_seconds = timeline_cache_ttl_seconds
        self._negative_ttl_seconds = timeline_not_found_ttl_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic_clock or time.perf_counter
        self._inflight: dict[tuple[Platform, str], asyncio.Task[TimelineLoadResult]] = {}

    async def get_timeline(self, *, platform: Platform, match_id: str) -> TimelineLoadResult:
        now = self._clock()
        cached = await self._repository.get_fresh(platform=platform, match_id=match_id, now=now)
        if cached is not None:
            if cached.result_status == "available":
                self._record_cache("hit")
                self._record_request("available")
                return TimelineLoadResult(
                    snapshot=TimelineSnapshot.model_validate(cached.normalized_snapshot),
                    cache_status="hit",
                )
            self._record_cache("not_found")
            self._record_request("not_found")
            raise _match_timeline_not_found()

        self._record_cache("miss")
        try:
            result = await self._load_single_flight(platform=platform, match_id=match_id)
        except ApiError as error:
            self._record_request(_request_outcome_for_error(error))
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            self._record_request("internal_error")
            raise
        self._record_request("available")
        return result

    async def _load_single_flight(self, *, platform: Platform, match_id: str) -> TimelineLoadResult:
        key = (platform, match_id)
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._load_shared(platform=platform, match_id=match_id))
            self._inflight[key] = task
            task.add_done_callback(lambda completed: self._clear_inflight(key, completed))
            self._record_singleflight("leader")
        else:
            self._record_singleflight("waiter")
        return await asyncio.shield(task)

    async def _load_shared(self, *, platform: Platform, match_id: str) -> TimelineLoadResult:
        try:
            result = await self._load_uncached(platform=platform, match_id=match_id)
        except Exception:
            self._record_singleflight("shared_failure")
            raise
        self._record_singleflight("shared_success")
        return result

    async def _load_uncached(self, *, platform: Platform, match_id: str) -> TimelineLoadResult:
        now = self._clock()
        cached = await self._repository.get_fresh(platform=platform, match_id=match_id, now=now)
        if cached is not None:
            if cached.result_status == "available":
                return TimelineLoadResult(
                    snapshot=TimelineSnapshot.model_validate(cached.normalized_snapshot),
                    cache_status="hit",
                )
            raise _match_timeline_not_found()

        started = self._monotonic()
        try:
            timeline = await self._gateway.get_match_timeline(platform=platform, match_id=match_id)
        except ApiError as error:
            elapsed = self._monotonic() - started
            if error.code == "MATCH_TIMELINE_NOT_FOUND":
                await self._repository.upsert(
                    _not_found_record(
                        platform=platform,
                        match_id=match_id,
                        now=now,
                        ttl_seconds=self._negative_ttl_seconds,
                    )
                )
                self._record_fetch("not_found", elapsed)
                raise _match_timeline_not_found() from error
            fetch_outcome = _fetch_outcome_for_error(error)
            if fetch_outcome is not None:
                self._record_fetch(fetch_outcome, elapsed)
            raise

        try:
            normalized = self._normalizer.normalize(platform=platform, timeline=timeline)
        except Exception as error:
            elapsed = self._monotonic() - started
            self._record_fetch("invalid_response", elapsed)
            raise ApiError(
                status_code=502,
                code="RIOT_INVALID_RESPONSE",
                message="Riot returned an invalid response.",
                retryable=False,
            ) from error

        elapsed = self._monotonic() - started
        record = _available_record(
            platform=platform,
            match_id=match_id,
            now=now,
            ttl_seconds=self._positive_ttl_seconds,
            normalized=normalized,
        )
        try:
            await self._repository.upsert(record)
        except Exception:
            # Never invent a Timeline 404 for a persistence failure.
            raise
        self._record_fetch("available", elapsed)
        self._record_events(normalized)
        return TimelineLoadResult(snapshot=normalized.snapshot, cache_status="miss")

    def _clear_inflight(
        self,
        key: tuple[Platform, str],
        completed: asyncio.Task[TimelineLoadResult],
    ) -> None:
        if self._inflight.get(key) is completed:
            del self._inflight[key]

    def _record_request(self, outcome: RequestOutcome) -> None:
        if outcome in self.REQUEST_OUTCOMES:
            self._metrics.joint_evidence_timeline_requests_total.inc(outcome=outcome)

    def _record_cache(self, status: CacheMetricStatus) -> None:
        if status in self.CACHE_STATUSES:
            self._metrics.joint_evidence_timeline_cache_total.inc(status=status)

    def _record_fetch(self, outcome: FetchOutcome, elapsed: float) -> None:
        if outcome in self.FETCH_OUTCOMES:
            self._metrics.joint_evidence_timeline_fetch_duration_seconds.observe(
                elapsed, outcome=outcome
            )

    def _record_singleflight(self, result: SingleflightResult) -> None:
        if result in self.SINGLEFLIGHT_RESULTS:
            self._metrics.joint_evidence_singleflight_total.inc(result=result)

    def _record_events(self, normalized: TimelineNormalizationResult) -> None:
        for event_type, count in normalized.supported_event_counts.items():
            if count <= 0 or event_type not in self.EVENT_TYPES:
                continue
            self._metrics.joint_evidence_timeline_events_total.inc(
                amount=float(count), event_type=event_type, result="supported"
            )
        participant_states = sum(
            1 for fact in normalized.snapshot.facts if isinstance(fact, ParticipantStateFact)
        )
        if participant_states > 0:
            self._metrics.joint_evidence_timeline_events_total.inc(
                amount=float(participant_states),
                event_type="participant_state",
                result="supported",
            )
        if normalized.ignored_event_count > 0:
            self._metrics.joint_evidence_timeline_events_total.inc(
                amount=float(normalized.ignored_event_count),
                event_type="unknown",
                result="ignored",
            )


def _match_timeline_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code="MATCH_TIMELINE_NOT_FOUND",
        message="Riot resource was not found.",
        retryable=False,
    )


def _request_outcome_for_error(error: ApiError) -> RequestOutcome:
    mapping: dict[str, RequestOutcome] = {
        "MATCH_TIMELINE_NOT_FOUND": "not_found",
        "RIOT_AUTH_FAILED": "auth_failed",
        "RIOT_RATE_LIMITED": "rate_limited",
        "RIOT_INVALID_RESPONSE": "invalid_response",
        "RIOT_UNAVAILABLE": "unavailable",
    }
    return mapping.get(error.code, "internal_error")


def _fetch_outcome_for_error(error: ApiError) -> FetchOutcome | None:
    mapping: dict[str, FetchOutcome] = {
        "MATCH_TIMELINE_NOT_FOUND": "not_found",
        "RIOT_AUTH_FAILED": "auth_failed",
        "RIOT_RATE_LIMITED": "rate_limited",
        "RIOT_INVALID_RESPONSE": "invalid_response",
        "RIOT_UNAVAILABLE": "unavailable",
    }
    return mapping.get(error.code)


def _available_record(
    *,
    platform: Platform,
    match_id: str,
    now: datetime,
    ttl_seconds: int,
    normalized: TimelineNormalizationResult,
) -> TimelineCacheRecord:
    return TimelineCacheRecord(
        platform=platform,
        match_id=match_id,
        result_status="available",
        normalized_snapshot=normalized.snapshot.model_dump(mode="json"),
        schema_version=TIMELINE_SCHEMA_VERSION,
        snapshot_hash=normalized.snapshot_hash,
        fetched_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        created_at=now,
        updated_at=now,
    )


def _not_found_record(
    *,
    platform: Platform,
    match_id: str,
    now: datetime,
    ttl_seconds: int,
) -> TimelineCacheRecord:
    return TimelineCacheRecord(
        platform=platform,
        match_id=match_id,
        result_status="not_found",
        normalized_snapshot=None,
        schema_version=TIMELINE_SCHEMA_VERSION,
        snapshot_hash=None,
        fetched_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        created_at=now,
        updated_at=now,
    )
