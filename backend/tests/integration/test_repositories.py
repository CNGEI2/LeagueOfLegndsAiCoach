from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.routing import Platform
from app.models.player import PlayerRow
from app.repositories.matches import MatchCacheConflict, SqlMatchRepository
from app.repositories.players import SqlPlayerRepository
from app.repositories.recent_matches import SqlRecentMatchRepository
from app.schemas.domain import MatchSnapshot, ParticipantSnapshot, PlayerProfile

pytestmark = pytest.mark.integration


def make_snapshot(*, match_id: str = "NA1_123", kills: int = 8) -> MatchSnapshot:
    return MatchSnapshot(
        match_id=match_id,
        platform=Platform.NA1,
        queue_id=420,
        game_version="16.15.1",
        started_at=datetime(2026, 7, 30, 12, tzinfo=UTC),
        duration_seconds=1800,
        participants=(
            ParticipantSnapshot(
                puuid="match-puuid",
                team_id=100,
                champion_id=103,
                role="MIDDLE",
                won=True,
                kills=kills,
                deaths=2,
                assists=6,
                cs=201,
                gold_earned=14321,
                damage_to_champions=24567,
                vision_score=18,
                item_ids=(1055, 6672, 3006),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_player_repository_respects_fresh_after(session_factory) -> None:
    repository = SqlPlayerRepository(session_factory)
    profile = PlayerProfile(
        puuid="integration-puuid",
        game_name="PlayerName",
        tag_line="1115",
        platform=Platform.NA1,
        summoner_level=50,
        profile_icon_id=29,
    )
    fetched_at = datetime.now(UTC)
    await repository.upsert(profile, fetched_at=fetched_at)

    fresh = await repository.get_by_riot_id(
        platform=Platform.NA1,
        game_name_key="playername",
        tag_line_key="1115",
        fresh_after=fetched_at - timedelta(seconds=1),
    )
    expired = await repository.get_by_riot_id(
        platform=Platform.NA1,
        game_name_key="playername",
        tag_line_key="1115",
        fresh_after=fetched_at + timedelta(seconds=1),
    )

    assert fresh == profile
    assert expired is None


@pytest.mark.asyncio
async def test_player_repository_enforces_unique_puuid(session_factory) -> None:
    fetched_at = datetime.now(UTC)
    first = PlayerRow(
        id=uuid4(),
        puuid="unique-puuid",
        platform=Platform.NA1.value,
        game_name="First",
        tag_line="NA1",
        game_name_key="first",
        tag_line_key="na1",
        summoner_level=1,
        profile_icon_id=1,
        fetched_at=fetched_at,
        updated_at=fetched_at,
    )
    duplicate = PlayerRow(
        id=uuid4(),
        puuid="unique-puuid",
        platform=Platform.NA1.value,
        game_name="Second",
        tag_line="NA1",
        game_name_key="second",
        tag_line_key="na1",
        summoner_level=2,
        profile_icon_id=2,
        fetched_at=fetched_at,
        updated_at=fetched_at,
    )
    async with session_factory() as session:
        session.add_all([first, duplicate])
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_recent_match_repository_preserves_match_id_order(session_factory) -> None:
    repository = SqlRecentMatchRepository(session_factory)
    now = datetime.now(UTC)
    match_ids = ("NA1_3", "NA1_1", "NA1_2")
    await repository.put(
        platform=Platform.NA1,
        puuid="recent-puuid",
        match_ids=match_ids,
        fetched_at=now,
        expires_at=now + timedelta(minutes=2),
    )

    assert await repository.get(platform=Platform.NA1, puuid="recent-puuid", now=now) == match_ids


@pytest.mark.asyncio
async def test_recent_match_repository_excludes_expired_rows(session_factory) -> None:
    repository = SqlRecentMatchRepository(session_factory)
    now = datetime.now(UTC)
    await repository.put(
        platform=Platform.NA1,
        puuid="expired-puuid",
        match_ids=("NA1_1",),
        fetched_at=now - timedelta(minutes=3),
        expires_at=now - timedelta(seconds=1),
    )

    assert await repository.get(platform=Platform.NA1, puuid="expired-puuid", now=now) is None


@pytest.mark.asyncio
async def test_match_repository_round_trips_validated_jsonb_snapshot(session_factory) -> None:
    repository = SqlMatchRepository(session_factory)
    snapshot = make_snapshot()
    fetched_at = datetime.now(UTC)
    await repository.put(snapshot, fetched_at=fetched_at)

    assert (
        await repository.get(
            platform=Platform.NA1,
            match_id=snapshot.match_id,
            fresh_after=fetched_at - timedelta(seconds=1),
        )
        == snapshot
    )


@pytest.mark.asyncio
async def test_match_repository_refreshes_identical_snapshot_without_overwriting_content(
    session_factory,
) -> None:
    repository = SqlMatchRepository(session_factory)
    snapshot = make_snapshot()
    first_fetched_at = datetime.now(UTC) - timedelta(minutes=1)
    refreshed_at = datetime.now(UTC)
    await repository.put(snapshot, fetched_at=first_fetched_at)
    await repository.put(snapshot, fetched_at=refreshed_at)

    assert (
        await repository.get(
            platform=Platform.NA1,
            match_id=snapshot.match_id,
            fresh_after=refreshed_at - timedelta(seconds=1),
        )
        == snapshot
    )


@pytest.mark.asyncio
async def test_match_repository_rejects_same_schema_content_conflict_without_overwrite(
    session_factory,
) -> None:
    repository = SqlMatchRepository(session_factory)
    original = make_snapshot(kills=8)
    conflicting = make_snapshot(kills=9)
    fetched_at = datetime.now(UTC)
    await repository.put(original, fetched_at=fetched_at)

    with pytest.raises(MatchCacheConflict):
        await repository.put(conflicting, fetched_at=fetched_at + timedelta(seconds=1))

    assert (
        await repository.get(
            platform=Platform.NA1,
            match_id=original.match_id,
            fresh_after=fetched_at - timedelta(seconds=1),
        )
        == original
    )


@pytest.mark.asyncio
async def test_match_repository_excludes_stale_snapshots_and_deletes_expired_rows(
    session_factory,
) -> None:
    repository = SqlMatchRepository(session_factory)
    snapshot = make_snapshot()
    fetched_at = datetime.now(UTC) - timedelta(days=31)
    await repository.put(snapshot, fetched_at=fetched_at)

    assert (
        await repository.get(
            platform=Platform.NA1,
            match_id=snapshot.match_id,
            fresh_after=fetched_at + timedelta(seconds=1),
        )
        is None
    )
    assert await repository.delete_expired(before=fetched_at + timedelta(seconds=1)) == 1
    assert (
        await repository.get(
            platform=Platform.NA1,
            match_id=snapshot.match_id,
            fresh_after=fetched_at - timedelta(seconds=1),
        )
        is None
    )
