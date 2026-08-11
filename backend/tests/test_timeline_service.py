from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ApiError
from app.core.metrics import MetricsRegistry
from app.core.routing import Platform
from app.repositories.timelines import TimelineCacheRecord
from app.services.riot.dto import TimelineDto, validate_timeline_payload
from app.services.timelines.domain import TIMELINE_SCHEMA_VERSION, TimelineSnapshot
from app.services.timelines.normalizer import TimelineNormalizer
from app.services.timelines.service import TimelineLoadResult, TimelineService
from tests.fixtures.riot_payloads import timeline_payload_for_normalizer

NOW = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)
POSITIVE_TTL = 2_592_000
NEGATIVE_TTL = 300


def _api_error(code: str, *, status_code: int = 502, retryable: bool = False) -> ApiError:
    return ApiError(
        status_code=status_code,
        code=code,
        message="safe upstream failure",
        retryable=retryable,
    )


class FakeTimelineRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[Platform, str], TimelineCacheRecord] = {}
        self.get_calls: list[tuple[Platform, str, datetime]] = []
        self.upserts: list[TimelineCacheRecord] = []
        self.upsert_error: Exception | None = None

    async def get_fresh(
        self, *, platform: Platform, match_id: str, now: datetime
    ) -> TimelineCacheRecord | None:
        self.get_calls.append((platform, match_id, now))
        record = self.records.get((platform, match_id))
        if record is None or record.expires_at <= now:
            return None
        return record

    async def upsert(self, record: TimelineCacheRecord) -> TimelineCacheRecord:
        if self.upsert_error is not None:
            raise self.upsert_error
        self.upserts.append(record)
        self.records[(record.platform, record.match_id)] = record
        return record


class FakeTimelineGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[Platform, str]] = []
        self.error: ApiError | None = None
        self.started: asyncio.Event | None = None
        self.release: asyncio.Event | None = None
        self.payload_match_id = "NA1_fixture"

    async def get_match_timeline(self, *, platform: Platform, match_id: str) -> TimelineDto:
        self.calls.append((platform, match_id))
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        payload = timeline_payload_for_normalizer(match_id=match_id)
        return validate_timeline_payload(payload, match_id=match_id)


class FakeNormalizer:
    def __init__(self) -> None:
        self._inner = TimelineNormalizer()
        self.calls = 0
        self.error: Exception | None = None

    def normalize(self, *, platform: Platform, timeline: TimelineDto):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self._inner.normalize(platform=platform, timeline=timeline)


class MutableClock:
    def __init__(self, current: datetime = NOW) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


class MonotonicClock:
    def __init__(self, values: list[float] | None = None) -> None:
        self._values = list(values or [100.0, 100.25, 100.5, 100.75, 101.0])
        self._index = 0

    def __call__(self) -> float:
        value = self._values[min(self._index, len(self._values) - 1)]
        self._index += 1
        return value


def make_service(
    *,
    repository: FakeTimelineRepository | None = None,
    gateway: FakeTimelineGateway | None = None,
    normalizer: FakeNormalizer | None = None,
    metrics: MetricsRegistry | None = None,
    clock: Callable[[], datetime] | None = None,
    monotonic: Callable[[], float] | None = None,
    positive_ttl: int = POSITIVE_TTL,
    negative_ttl: int = NEGATIVE_TTL,
) -> tuple[TimelineService, FakeTimelineRepository, FakeTimelineGateway, FakeNormalizer]:
    repository = repository or FakeTimelineRepository()
    gateway = gateway or FakeTimelineGateway()
    normalizer = normalizer or FakeNormalizer()
    service = TimelineService(
        repository=repository,
        gateway=gateway,
        normalizer=normalizer,
        metrics=metrics or MetricsRegistry(),
        timeline_cache_ttl_seconds=positive_ttl,
        timeline_not_found_ttl_seconds=negative_ttl,
        clock=clock or MutableClock(),
        monotonic_clock=monotonic or MonotonicClock(),
    )
    return service, repository, gateway, normalizer


def _available_record(
    *,
    platform: Platform,
    match_id: str,
    fetched_at: datetime,
    expires_at: datetime,
) -> TimelineCacheRecord:
    payload = timeline_payload_for_normalizer(match_id=match_id)
    dto = validate_timeline_payload(payload, match_id=match_id)
    result = TimelineNormalizer().normalize(platform=platform, timeline=dto)
    return TimelineCacheRecord(
        platform=platform,
        match_id=match_id,
        result_status="available",
        normalized_snapshot=result.snapshot.model_dump(mode="json"),
        schema_version=TIMELINE_SCHEMA_VERSION,
        snapshot_hash=result.snapshot_hash,
        fetched_at=fetched_at,
        expires_at=expires_at,
        created_at=fetched_at,
        updated_at=fetched_at,
    )


def _not_found_record(
    *,
    platform: Platform,
    match_id: str,
    fetched_at: datetime,
    expires_at: datetime,
) -> TimelineCacheRecord:
    return TimelineCacheRecord(
        platform=platform,
        match_id=match_id,
        result_status="not_found",
        normalized_snapshot=None,
        schema_version=TIMELINE_SCHEMA_VERSION,
        snapshot_hash=None,
        fetched_at=fetched_at,
        expires_at=expires_at,
        created_at=fetched_at,
        updated_at=fetched_at,
    )


@pytest.mark.asyncio
async def test_positive_cache_hit_miss_expiry_and_exact_ttl() -> None:
    clock = MutableClock(NOW)
    service, repository, gateway, normalizer = make_service(clock=clock)

    first = await service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")
    assert isinstance(first, TimelineLoadResult)
    assert first.cache_status == "miss"
    assert isinstance(first.snapshot, TimelineSnapshot)
    assert gateway.calls == [(Platform.NA1, "NA1_fixture")]
    assert normalizer.calls == 1
    assert len(repository.upserts) == 1
    stored = repository.upserts[0]
    assert stored.result_status == "available"
    assert stored.fetched_at == NOW
    assert stored.expires_at == NOW + timedelta(seconds=POSITIVE_TTL)
    assert stored.expires_at - stored.fetched_at == timedelta(seconds=2_592_000)

    second = await service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")
    assert second.cache_status == "hit"
    assert second.snapshot == first.snapshot
    assert gateway.calls == [(Platform.NA1, "NA1_fixture")]
    assert normalizer.calls == 1

    clock.current = stored.expires_at
    assert (
        await repository.get_fresh(platform=Platform.NA1, match_id="NA1_fixture", now=clock.current)
        is None
    )
    third = await service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")
    assert third.cache_status == "miss"
    assert gateway.calls == [(Platform.NA1, "NA1_fixture"), (Platform.NA1, "NA1_fixture")]
    assert normalizer.calls == 2


@pytest.mark.asyncio
async def test_negative_cache_hit_miss_expiry_exact_ttl_and_reraise() -> None:
    clock = MutableClock(NOW)
    gateway = FakeTimelineGateway()
    gateway.error = _api_error("MATCH_TIMELINE_NOT_FOUND", status_code=404)
    service, repository, _, _ = make_service(clock=clock, gateway=gateway)

    with pytest.raises(ApiError) as first:
        await service.get_timeline(platform=Platform.NA1, match_id="NA1_missing")
    assert first.value.code == "MATCH_TIMELINE_NOT_FOUND"
    assert first.value.status_code == 404
    assert first.value.retryable is False
    assert len(repository.upserts) == 1
    stored = repository.upserts[0]
    assert stored.result_status == "not_found"
    assert stored.normalized_snapshot is None
    assert stored.snapshot_hash is None
    assert stored.expires_at - stored.fetched_at == timedelta(seconds=300)
    assert gateway.calls == [(Platform.NA1, "NA1_missing")]

    with pytest.raises(ApiError) as cached:
        await service.get_timeline(platform=Platform.NA1, match_id="NA1_missing")
    assert cached.value.code == "MATCH_TIMELINE_NOT_FOUND"
    assert gateway.calls == [(Platform.NA1, "NA1_missing")]

    clock.current = stored.expires_at
    with pytest.raises(ApiError) as refreshed:
        await service.get_timeline(platform=Platform.NA1, match_id="NA1_missing")
    assert refreshed.value.code == "MATCH_TIMELINE_NOT_FOUND"
    assert gateway.calls == [(Platform.NA1, "NA1_missing"), (Platform.NA1, "NA1_missing")]
    assert len(repository.upserts) == 2


@pytest.mark.asyncio
async def test_expires_at_equal_to_now_is_treated_as_expired() -> None:
    clock = MutableClock(NOW)
    service, repository, gateway, _ = make_service(clock=clock)
    await repository.upsert(
        _available_record(
            platform=Platform.NA1,
            match_id="NA1_boundary",
            fetched_at=NOW - timedelta(seconds=10),
            expires_at=NOW,
        )
    )

    result = await service.get_timeline(platform=Platform.NA1, match_id="NA1_boundary")
    assert result.cache_status == "miss"
    assert gateway.calls == [(Platform.NA1, "NA1_boundary")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "status_code", "retryable"),
    [
        ("RIOT_AUTH_FAILED", 503, False),
        ("RIOT_RATE_LIMITED", 429, True),
        ("RIOT_UNAVAILABLE", 503, True),
        ("RIOT_INVALID_RESPONSE", 502, False),
    ],
)
async def test_non_not_found_upstream_errors_do_not_write_negative_cache(
    code: str, status_code: int, retryable: bool
) -> None:
    gateway = FakeTimelineGateway()
    gateway.error = _api_error(code, status_code=status_code, retryable=retryable)
    service, repository, _, _ = make_service(gateway=gateway)

    with pytest.raises(ApiError) as raised:
        await service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")
    assert raised.value.code == code
    assert raised.value.status_code == status_code
    assert repository.upserts == []
    assert raised.value.code != "MATCH_TIMELINE_NOT_FOUND"


@pytest.mark.asyncio
async def test_normalizer_failure_does_not_write_cache_or_fake_timeline_404() -> None:
    normalizer = FakeNormalizer()
    normalizer.error = RuntimeError("normalize boom")
    service, repository, gateway, _ = make_service(normalizer=normalizer)

    with pytest.raises(ApiError) as raised:
        await service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")
    assert raised.value.code == "RIOT_INVALID_RESPONSE"
    assert raised.value.code != "MATCH_TIMELINE_NOT_FOUND"
    assert repository.upserts == []
    assert gateway.calls == [(Platform.NA1, "NA1_fixture")]


@pytest.mark.asyncio
async def test_repository_write_failure_does_not_write_negative_or_fake_404() -> None:
    repository = FakeTimelineRepository()
    repository.upsert_error = RuntimeError("db write failed")
    service, repository, gateway, normalizer = make_service(repository=repository)

    with pytest.raises(Exception) as raised:
        await service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")
    assert "MATCH_TIMELINE_NOT_FOUND" not in str(raised.value)
    if isinstance(raised.value, ApiError):
        assert raised.value.code != "MATCH_TIMELINE_NOT_FOUND"
    assert repository.upserts == []
    assert gateway.calls == [(Platform.NA1, "NA1_fixture")]
    assert normalizer.calls == 1
    assert repository.records == {}


@pytest.mark.asyncio
async def test_identical_misses_share_one_gateway_request_via_event_barrier() -> None:
    gateway = FakeTimelineGateway()
    gateway.started = asyncio.Event()
    gateway.release = asyncio.Event()
    service, repository, _, normalizer = make_service(gateway=gateway)

    first = asyncio.create_task(service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture"))
    await gateway.started.wait()
    second = asyncio.create_task(
        service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")
    )
    await asyncio.sleep(0)
    gateway.release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert first_result.snapshot == second_result.snapshot
    assert gateway.calls == [(Platform.NA1, "NA1_fixture")]
    assert normalizer.calls == 1
    assert len(repository.upserts) == 1
    assert service._inflight == {}


@pytest.mark.asyncio
async def test_different_match_or_platform_do_not_share_single_flight() -> None:
    gateway = FakeTimelineGateway()
    gateway.started = asyncio.Event()
    gateway.release = asyncio.Event()
    service, _, _, _ = make_service(gateway=gateway)

    first = asyncio.create_task(service.get_timeline(platform=Platform.NA1, match_id="NA1_one"))
    await gateway.started.wait()
    # Reset started so the second leader can signal independently after release.
    gateway.started = asyncio.Event()
    second = asyncio.create_task(service.get_timeline(platform=Platform.EUW1, match_id="NA1_one"))
    third = asyncio.create_task(service.get_timeline(platform=Platform.NA1, match_id="NA1_two"))
    await asyncio.sleep(0)
    gateway.release.set()
    await asyncio.gather(first, second, third)

    assert sorted(gateway.calls) == sorted(
        [
            (Platform.NA1, "NA1_one"),
            (Platform.EUW1, "NA1_one"),
            (Platform.NA1, "NA1_two"),
        ]
    )
    assert service._inflight == {}


@pytest.mark.asyncio
async def test_cancelling_one_waiter_does_not_cancel_shared_request() -> None:
    gateway = FakeTimelineGateway()
    gateway.started = asyncio.Event()
    gateway.release = asyncio.Event()
    service, _, _, _ = make_service(gateway=gateway)

    first = asyncio.create_task(service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture"))
    await gateway.started.wait()
    second = asyncio.create_task(
        service.get_timeline(platform=Platform.NA1, match_id="NA1_fixture")
    )
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    gateway.release.set()
    second_result = await second
    assert second_result.cache_status == "miss"
    assert gateway.calls == [(Platform.NA1, "NA1_fixture")]
    assert service._inflight == {}


@pytest.mark.asyncio
async def test_inflight_cleared_after_success_failure_normalizer_error_and_shared_cancel() -> None:
    service, _, gateway, normalizer = make_service()
    await service.get_timeline(platform=Platform.NA1, match_id="NA1_ok")
    assert service._inflight == {}

    gateway.error = _api_error("RIOT_UNAVAILABLE", status_code=503, retryable=True)
    with pytest.raises(ApiError):
        await service.get_timeline(platform=Platform.NA1, match_id="NA1_fail")
    assert service._inflight == {}

    gateway.error = None
    normalizer.error = RuntimeError("normalize failed")
    with pytest.raises(ApiError):
        await service.get_timeline(platform=Platform.NA1, match_id="NA1_bad")
    assert service._inflight == {}
    normalizer.error = None

    gateway.started = asyncio.Event()
    gateway.release = asyncio.Event()
    leader = asyncio.create_task(
        service.get_timeline(platform=Platform.NA1, match_id="NA1_cancel_shared")
    )
    await gateway.started.wait()
    shared = next(iter(service._inflight.values()))
    shared.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leader
    assert service._inflight == {}
    gateway.release.set()

    retry = await service.get_timeline(platform=Platform.NA1, match_id="NA1_cancel_shared")
    assert retry.cache_status == "miss"
    assert (Platform.NA1, "NA1_cancel_shared") in gateway.calls


@pytest.mark.asyncio
async def test_leader_rechecks_repository_before_upstream_fetch() -> None:
    clock = MutableClock(NOW)

    class RecheckRepository(FakeTimelineRepository):
        def __init__(self) -> None:
            super().__init__()
            self.gets = 0

        async def get_fresh(
            self, *, platform: Platform, match_id: str, now: datetime
        ) -> TimelineCacheRecord | None:
            self.gets += 1
            if self.gets == 1:
                return None
            if self.gets == 2:
                record = _available_record(
                    platform=platform,
                    match_id=match_id,
                    fetched_at=now,
                    expires_at=now + timedelta(days=30),
                )
                self.records[(platform, match_id)] = record
                return record
            return await super().get_fresh(platform=platform, match_id=match_id, now=now)

    repository = RecheckRepository()
    gateway = FakeTimelineGateway()
    service, _, _, normalizer = make_service(repository=repository, gateway=gateway, clock=clock)
    result = await service.get_timeline(platform=Platform.NA1, match_id="NA1_race")
    assert result.cache_status == "hit"
    assert gateway.calls == []
    assert normalizer.calls == 0
    assert repository.gets >= 2
