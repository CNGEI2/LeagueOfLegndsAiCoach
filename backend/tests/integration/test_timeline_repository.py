import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.errors import ApiError
from app.core.routing import Platform
from app.repositories.timelines import SqlTimelineRepository, TimelineCacheRecord
from app.services.riot.dto import validate_timeline_payload
from app.services.timelines.domain import TIMELINE_SCHEMA_VERSION
from app.services.timelines.normalizer import TimelineNormalizer
from tests.fixtures.riot_payloads import (
    timeline_payload_for_normalizer,
    timeline_payload_with_optional_gaps,
)

pytestmark = pytest.mark.integration


def _now() -> datetime:
    return datetime.now(UTC)


def uuid_hex() -> str:
    return uuid4().hex


def _available_snapshot(
    *,
    platform: Platform = Platform.NA1,
    match_id: str,
    payload: dict[str, object] | None = None,
) -> tuple[dict[str, object], str]:
    raw = timeline_payload_for_normalizer(match_id=match_id) if payload is None else payload
    timeline = validate_timeline_payload(raw, match_id=match_id)
    result = TimelineNormalizer().normalize(platform=platform, timeline=timeline)
    return result.snapshot.model_dump(mode="json"), result.snapshot_hash


def make_record(**overrides: object) -> TimelineCacheRecord:
    now = _now()
    match_id = str(overrides.get("match_id", "NA1_timeline_cache"))
    platform = overrides.get("platform", Platform.NA1)
    assert isinstance(platform, Platform)
    snapshot, snapshot_hash = _available_snapshot(platform=platform, match_id=match_id)
    values: dict[str, object] = {
        "platform": platform,
        "match_id": match_id,
        "result_status": "available",
        "normalized_snapshot": snapshot,
        "schema_version": TIMELINE_SCHEMA_VERSION,
        "snapshot_hash": snapshot_hash,
        "fetched_at": now,
        "expires_at": now + timedelta(days=30),
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return TimelineCacheRecord(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_timeline_repository_round_trips_positive_and_negative_records(
    session_factory,
) -> None:
    repository = SqlTimelineRepository(session_factory)
    now = _now()
    positive = make_record(
        match_id=f"NA1_pos_{now.timestamp()}",
        fetched_at=now,
        expires_at=now + timedelta(days=30),
        created_at=now,
        updated_at=now,
    )
    negative = make_record(
        match_id=f"NA1_neg_{now.timestamp()}",
        result_status="not_found",
        normalized_snapshot=None,
        snapshot_hash=None,
        fetched_at=now,
        expires_at=now + timedelta(minutes=5),
        created_at=now,
        updated_at=now,
    )

    stored_positive = await repository.upsert(positive)
    stored_negative = await repository.upsert(negative)
    assert stored_positive == positive
    assert stored_negative == negative
    assert stored_positive.fetched_at.tzinfo is not None
    assert stored_negative.expires_at.tzinfo is not None

    assert (
        await repository.get_fresh(platform=positive.platform, match_id=positive.match_id, now=now)
        == positive
    )
    assert (
        await repository.get_fresh(platform=negative.platform, match_id=negative.match_id, now=now)
        == negative
    )


@pytest.mark.asyncio
async def test_timeline_repository_get_fresh_requires_expires_at_strictly_after_now(
    session_factory,
) -> None:
    repository = SqlTimelineRepository(session_factory)
    now = _now()
    record = make_record(
        match_id=f"NA1_boundary_{now.timestamp()}",
        fetched_at=now - timedelta(minutes=1),
        expires_at=now,
        created_at=now - timedelta(minutes=1),
        updated_at=now - timedelta(minutes=1),
    )
    await repository.upsert(record)

    assert (
        await repository.get_fresh(platform=record.platform, match_id=record.match_id, now=now)
        is None
    )
    assert (
        await repository.get_fresh(
            platform=record.platform,
            match_id=record.match_id,
            now=now - timedelta(seconds=1),
        )
        == record
    )


@pytest.mark.asyncio
async def test_timeline_repository_isolates_same_match_id_across_platforms(
    session_factory,
) -> None:
    repository = SqlTimelineRepository(session_factory)
    now = _now()
    match_id = f"SHARED_{uuid_hex()}"
    na_snapshot, na_hash = _available_snapshot(platform=Platform.NA1, match_id=match_id)
    euw_snapshot, euw_hash = _available_snapshot(platform=Platform.EUW1, match_id=match_id)
    na = make_record(
        platform=Platform.NA1,
        match_id=match_id,
        normalized_snapshot=na_snapshot,
        snapshot_hash=na_hash,
        fetched_at=now,
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    euw = make_record(
        platform=Platform.EUW1,
        match_id=match_id,
        normalized_snapshot=euw_snapshot,
        snapshot_hash=euw_hash,
        fetched_at=now,
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )

    await repository.upsert(na)
    await repository.upsert(euw)

    assert (
        await repository.get_fresh(platform=Platform.NA1, match_id=match_id, now=now)
    ).snapshot_hash == na_hash  # type: ignore[union-attr]
    assert (
        await repository.get_fresh(platform=Platform.EUW1, match_id=match_id, now=now)
    ).snapshot_hash == euw_hash  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_timeline_repository_repeated_identical_upsert_preserves_created_at(
    session_factory,
) -> None:
    repository = SqlTimelineRepository(session_factory)
    created = _now() - timedelta(hours=2)
    first = make_record(
        match_id=f"NA1_repeat_{created.timestamp()}",
        fetched_at=created,
        expires_at=created + timedelta(days=1),
        created_at=created,
        updated_at=created,
    )
    stored_first = await repository.upsert(first)

    later = _now()
    second = make_record(
        platform=first.platform,
        match_id=first.match_id,
        normalized_snapshot=first.normalized_snapshot,
        snapshot_hash=first.snapshot_hash,
        fetched_at=later,
        expires_at=later + timedelta(days=1),
        created_at=later,
        updated_at=later,
    )
    stored_second = await repository.upsert(second)

    assert stored_second.created_at == stored_first.created_at == created
    assert stored_second.fetched_at == later
    assert stored_second.updated_at == later


@pytest.mark.asyncio
async def test_timeline_repository_replaces_positive_and_negative_shapes(
    session_factory,
) -> None:
    repository = SqlTimelineRepository(session_factory)
    now = _now()
    match_id = f"NA1_flip_{now.timestamp()}"
    positive = make_record(
        match_id=match_id,
        fetched_at=now,
        expires_at=now + timedelta(days=1),
        created_at=now,
        updated_at=now,
    )
    await repository.upsert(positive)

    negative = make_record(
        match_id=match_id,
        result_status="not_found",
        normalized_snapshot=None,
        snapshot_hash=None,
        fetched_at=now + timedelta(seconds=1),
        expires_at=now + timedelta(minutes=5),
        created_at=now + timedelta(seconds=1),
        updated_at=now + timedelta(seconds=1),
    )
    stored_negative = await repository.upsert(negative)
    assert stored_negative.result_status == "not_found"
    assert stored_negative.normalized_snapshot is None
    assert stored_negative.snapshot_hash is None
    assert stored_negative.created_at == positive.created_at

    alt_payload = timeline_payload_with_optional_gaps()
    alt_payload["metadata"]["matchId"] = match_id
    restored_snapshot, restored_hash = _available_snapshot(
        platform=Platform.NA1,
        match_id=match_id,
        payload=alt_payload,
    )
    restored = make_record(
        match_id=match_id,
        normalized_snapshot=restored_snapshot,
        snapshot_hash=restored_hash,
        fetched_at=now + timedelta(seconds=2),
        expires_at=now + timedelta(days=2),
        created_at=now + timedelta(seconds=2),
        updated_at=now + timedelta(seconds=2),
    )
    stored_restored = await repository.upsert(restored)
    assert stored_restored.result_status == "available"
    assert stored_restored.snapshot_hash == restored_hash
    assert stored_restored.created_at == positive.created_at


@pytest.mark.asyncio
async def test_timeline_repository_concurrent_upsert_converges_without_integrity_error(
    session_factory,
) -> None:
    repository = SqlTimelineRepository(session_factory)
    now = _now()
    match_id = f"NA1_concurrent_{uuid_hex()}"
    left_snapshot, left_hash = _available_snapshot(platform=Platform.NA1, match_id=match_id)
    right_payload = timeline_payload_with_optional_gaps()
    right_payload["metadata"]["matchId"] = match_id
    right_snapshot, right_hash = _available_snapshot(
        platform=Platform.NA1,
        match_id=match_id,
        payload=right_payload,
    )
    left = make_record(
        match_id=match_id,
        snapshot_hash=left_hash,
        normalized_snapshot=left_snapshot,
        fetched_at=now,
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    right = make_record(
        match_id=match_id,
        snapshot_hash=right_hash,
        normalized_snapshot=right_snapshot,
        fetched_at=now + timedelta(milliseconds=1),
        expires_at=now + timedelta(hours=1),
        created_at=now + timedelta(milliseconds=1),
        updated_at=now + timedelta(milliseconds=1),
    )

    try:
        results = await asyncio.gather(repository.upsert(left), repository.upsert(right))
    except IntegrityError as error:
        raise AssertionError("concurrent timeline upsert raised IntegrityError") from error

    assert {result.match_id for result in results} == {match_id}
    fresh = await repository.get_fresh(platform=Platform.NA1, match_id=match_id, now=now)
    assert fresh is not None
    assert fresh.snapshot_hash in {left_hash, right_hash}


@pytest.mark.asyncio
async def test_timeline_repository_rejects_available_snapshot_hash_mismatch(
    session_factory,
) -> None:
    repository = SqlTimelineRepository(session_factory)
    now = _now()
    match_id = f"NA1_bad_hash_{uuid_hex()}"
    record = make_record(
        match_id=match_id,
        snapshot_hash="0" * 64,
        fetched_at=now,
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    await repository.upsert(record)

    with pytest.raises(ApiError) as error:
        await repository.get_fresh(platform=Platform.NA1, match_id=match_id, now=now)
    assert error.value.code == "RIOT_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_timeline_repository_rejects_available_identity_mismatch(
    session_factory,
) -> None:
    repository = SqlTimelineRepository(session_factory)
    now = _now()
    match_id = f"NA1_bad_identity_{uuid_hex()}"
    snapshot, snapshot_hash = _available_snapshot(platform=Platform.NA1, match_id=match_id)
    snapshot["match_id"] = f"{match_id}_other"
    record = make_record(
        match_id=match_id,
        normalized_snapshot=snapshot,
        snapshot_hash=snapshot_hash,
        fetched_at=now,
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    await repository.upsert(record)

    with pytest.raises(ApiError) as error:
        await repository.get_fresh(platform=Platform.NA1, match_id=match_id, now=now)
    assert error.value.code == "RIOT_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_timeline_repository_rejects_available_schema_corruption(
    session_factory,
) -> None:
    repository = SqlTimelineRepository(session_factory)
    now = _now()
    match_id = f"NA1_bad_schema_{uuid_hex()}"
    record = make_record(
        match_id=match_id,
        normalized_snapshot={"schema_version": 1, "facts": []},
        snapshot_hash="a" * 64,
        fetched_at=now,
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    await repository.upsert(record)

    with pytest.raises(ApiError) as error:
        await repository.get_fresh(platform=Platform.NA1, match_id=match_id, now=now)
    assert error.value.code == "RIOT_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_timeline_repository_not_found_skips_snapshot_validation(
    session_factory,
) -> None:
    repository = SqlTimelineRepository(session_factory)
    now = _now()
    match_id = f"NA1_not_found_ok_{uuid_hex()}"
    negative = make_record(
        match_id=match_id,
        result_status="not_found",
        normalized_snapshot=None,
        snapshot_hash=None,
        fetched_at=now,
        expires_at=now + timedelta(minutes=5),
        created_at=now,
        updated_at=now,
    )
    await repository.upsert(negative)
    loaded = await repository.get_fresh(platform=Platform.NA1, match_id=match_id, now=now)
    assert loaded == negative
