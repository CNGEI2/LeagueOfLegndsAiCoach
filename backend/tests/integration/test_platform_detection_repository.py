from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.routing import Platform, ordered_platforms
from app.repositories.platform_detections import (
    DetectionStatus,
    PlatformDetectionRecord,
    SqlPlatformDetectionRepository,
)

pytestmark = pytest.mark.integration


def _now() -> datetime:
    return datetime.now(UTC)


def make_record(**overrides: object) -> PlatformDetectionRecord:
    now = _now()
    values: dict[str, object] = {
        "id": uuid4(),
        "game_name_key": "player",
        "tag_line_key": "na1",
        "canonical_game_name": "Player",
        "canonical_tag_line": "NA1",
        "puuid": "detection-puuid",
        "status": DetectionStatus.RESOLVED,
        "candidate_platforms": (Platform.NA1,),
        "fetched_at": now,
        "expires_at": now + timedelta(hours=24),
        "confirmation_expires_at": None,
    }
    values.update(overrides)
    return PlatformDetectionRecord(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_platform_detection_repository_round_trips_resolved_record(session_factory) -> None:
    repository = SqlPlatformDetectionRepository(session_factory)
    record = make_record(
        game_name_key=f"resolved-{uuid4().hex}",
        status=DetectionStatus.RESOLVED,
        puuid="resolved-puuid",
        candidate_platforms=(Platform.NA1,),
        confirmation_expires_at=None,
    )

    stored = await repository.upsert(record)
    assert stored == record

    fresh = await repository.get_fresh(
        game_name_key=record.game_name_key,
        tag_line_key=record.tag_line_key,
        now=record.fetched_at,
    )
    assert fresh == record


@pytest.mark.asyncio
async def test_platform_detection_repository_round_trips_ambiguous_record(session_factory) -> None:
    repository = SqlPlatformDetectionRepository(session_factory)
    now = _now()
    record = make_record(
        game_name_key=f"ambiguous-{uuid4().hex}",
        status=DetectionStatus.AMBIGUOUS,
        puuid="ambiguous-puuid",
        candidate_platforms=(Platform.EUW1, Platform.NA1),
        fetched_at=now,
        expires_at=now + timedelta(hours=24),
        confirmation_expires_at=now + timedelta(minutes=15),
    )

    stored = await repository.upsert(record)
    assert stored.candidate_platforms == (Platform.EUW1, Platform.NA1)

    confirmed = await repository.get_for_confirmation(detection_id=stored.id, now=now)
    assert confirmed == stored


@pytest.mark.asyncio
async def test_platform_detection_repository_round_trips_not_found_record(session_factory) -> None:
    repository = SqlPlatformDetectionRepository(session_factory)
    record = make_record(
        game_name_key=f"missing-{uuid4().hex}",
        canonical_game_name=None,
        canonical_tag_line=None,
        status=DetectionStatus.NOT_FOUND,
        puuid=None,
        candidate_platforms=(),
        confirmation_expires_at=None,
    )

    stored = await repository.upsert(record)
    fresh = await repository.get_fresh(
        game_name_key=record.game_name_key,
        tag_line_key=record.tag_line_key,
        now=record.fetched_at,
    )
    assert fresh == stored
    assert fresh is not None
    assert fresh.status is DetectionStatus.NOT_FOUND
    assert fresh.puuid is None
    assert fresh.candidate_platforms == ()


@pytest.mark.asyncio
async def test_platform_detection_get_fresh_excludes_expired_rows(session_factory) -> None:
    repository = SqlPlatformDetectionRepository(session_factory)
    now = _now()
    record = make_record(
        game_name_key=f"expired-{uuid4().hex}",
        fetched_at=now - timedelta(hours=25),
        expires_at=now,
    )
    await repository.upsert(record)

    assert (
        await repository.get_fresh(
            game_name_key=record.game_name_key,
            tag_line_key=record.tag_line_key,
            now=now,
        )
        is None
    )


@pytest.mark.asyncio
async def test_platform_detection_get_for_confirmation_requires_both_deadlines(
    session_factory,
) -> None:
    repository = SqlPlatformDetectionRepository(session_factory)
    now = _now()
    record = make_record(
        game_name_key=f"confirm-{uuid4().hex}",
        status=DetectionStatus.AMBIGUOUS,
        puuid="confirm-puuid",
        candidate_platforms=(Platform.KR, Platform.NA1),
        fetched_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=23),
        confirmation_expires_at=now,
    )
    await repository.upsert(record)

    assert await repository.get_for_confirmation(detection_id=record.id, now=now) is None

    still_fresh = await repository.get_fresh(
        game_name_key=record.game_name_key,
        tag_line_key=record.tag_line_key,
        now=now,
    )
    assert still_fresh is not None


@pytest.mark.asyncio
async def test_platform_detection_upsert_sorts_candidates_by_catalog_order(
    session_factory,
) -> None:
    repository = SqlPlatformDetectionRepository(session_factory)
    now = _now()
    unordered = (Platform.VN2, Platform.BR1, Platform.KR, Platform.NA1)
    expected = tuple(platform for platform in ordered_platforms() if platform in unordered)
    record = make_record(
        game_name_key=f"ordered-{uuid4().hex}",
        status=DetectionStatus.AMBIGUOUS,
        puuid="ordered-puuid",
        candidate_platforms=unordered,
        fetched_at=now,
        expires_at=now + timedelta(hours=1),
        confirmation_expires_at=now + timedelta(minutes=15),
    )

    stored = await repository.upsert(record)
    assert stored.candidate_platforms == expected
    assert expected == (Platform.BR1, Platform.KR, Platform.NA1, Platform.VN2)


@pytest.mark.asyncio
async def test_platform_detection_repeated_upsert_converges_on_same_key(session_factory) -> None:
    repository = SqlPlatformDetectionRepository(session_factory)
    key = f"repeat-{uuid4().hex}"
    first = make_record(
        id=uuid4(),
        game_name_key=key,
        puuid="first-puuid",
        candidate_platforms=(Platform.NA1,),
        canonical_game_name="First",
    )
    second = make_record(
        id=uuid4(),
        game_name_key=key,
        puuid="second-puuid",
        candidate_platforms=(Platform.EUW1,),
        canonical_game_name="Second",
        fetched_at=first.fetched_at + timedelta(seconds=5),
        expires_at=first.expires_at + timedelta(seconds=5),
    )

    stored_first = await repository.upsert(first)
    stored_second = await repository.upsert(second)

    assert stored_second.game_name_key == key
    assert stored_second.puuid == "second-puuid"
    assert stored_second.canonical_game_name == "Second"
    assert stored_second.id == stored_first.id


@pytest.mark.asyncio
async def test_platform_detection_concurrent_upsert_converges(session_factory) -> None:
    import asyncio

    repository = SqlPlatformDetectionRepository(session_factory)
    key = f"concurrent-{uuid4().hex}"
    now = _now()
    left = make_record(
        id=uuid4(),
        game_name_key=key,
        puuid="left-puuid",
        candidate_platforms=(Platform.NA1,),
        fetched_at=now,
        expires_at=now + timedelta(hours=1),
        canonical_game_name="Left",
    )
    right = make_record(
        id=uuid4(),
        game_name_key=key,
        puuid="right-puuid",
        candidate_platforms=(Platform.EUW1,),
        fetched_at=now + timedelta(milliseconds=1),
        expires_at=now + timedelta(hours=1),
        canonical_game_name="Right",
    )

    results = await asyncio.gather(repository.upsert(left), repository.upsert(right))
    assert {result.game_name_key for result in results} == {key}

    fresh = await repository.get_fresh(
        game_name_key=key,
        tag_line_key=left.tag_line_key,
        now=now,
    )
    assert fresh is not None
    assert fresh.puuid in {"left-puuid", "right-puuid"}
    assert fresh.id in {left.id, right.id, results[0].id, results[1].id}


@pytest.mark.asyncio
async def test_platform_detection_delete_removes_row(session_factory) -> None:
    repository = SqlPlatformDetectionRepository(session_factory)
    record = make_record(game_name_key=f"delete-{uuid4().hex}")
    await repository.upsert(record)

    await repository.delete(detection_id=record.id)

    assert (
        await repository.get_fresh(
            game_name_key=record.game_name_key,
            tag_line_key=record.tag_line_key,
            now=record.fetched_at,
        )
        is None
    )
    assert (
        await repository.get_for_confirmation(detection_id=record.id, now=record.fetched_at) is None
    )


@pytest.mark.asyncio
async def test_platform_detection_record_rejects_invalid_resolved_shape() -> None:
    with pytest.raises(ValueError):
        make_record(
            status=DetectionStatus.RESOLVED, candidate_platforms=(Platform.NA1, Platform.EUW1)
        )

    with pytest.raises(ValueError):
        make_record(
            status=DetectionStatus.RESOLVED, puuid=None, candidate_platforms=(Platform.NA1,)
        )

    with pytest.raises(ValueError):
        make_record(
            status=DetectionStatus.AMBIGUOUS,
            candidate_platforms=(Platform.NA1,),
            confirmation_expires_at=_now() + timedelta(minutes=15),
        )

    with pytest.raises(ValueError):
        make_record(
            status=DetectionStatus.NOT_FOUND,
            puuid="should-be-none",
            candidate_platforms=(),
        )
