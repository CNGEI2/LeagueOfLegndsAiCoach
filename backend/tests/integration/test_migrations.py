import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

pytestmark = pytest.mark.integration


def _alembic_config(test_database_url: str) -> Config:
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", test_database_url)
    return config


async def _table_names(test_database_url: str) -> set[str]:
    engine = create_async_engine(test_database_url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
    finally:
        await engine.dispose()
    return set(tables)


async def _column_names(test_database_url: str, table_name: str) -> set[str]:
    engine = create_async_engine(test_database_url)
    try:
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync_connection: {
                    column["name"] for column in inspect(sync_connection).get_columns(table_name)
                }
            )
    finally:
        await engine.dispose()
    return columns


async def _player_constraints(test_database_url: str) -> tuple[list[dict], list[dict]]:
    engine = create_async_engine(test_database_url)
    try:
        async with engine.connect() as connection:

            def reflect(sync_connection):  # type: ignore[no-untyped-def]
                inspector = inspect(sync_connection)
                return (
                    inspector.get_unique_constraints("players"),
                    inspector.get_indexes("players"),
                )

            return await connection.run_sync(reflect)
    finally:
        await engine.dispose()


async def _truncate_players(test_database_url: str) -> None:
    engine = create_async_engine(test_database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE TABLE players CASCADE"))
    finally:
        await engine.dispose()


async def _restore_head(test_database_url: str, config: Config) -> None:
    """Return the shared test database to head with player uniqueness downgrade-safe."""
    await _truncate_players(test_database_url)
    await asyncio.to_thread(command.upgrade, config, "head")


def _has_unique_on(constraints: list[dict], columns: list[str]) -> bool:
    return any(constraint["column_names"] == columns for constraint in constraints)


def _has_index_on(indexes: list[dict], columns: list[str], *, unique: bool | None = None) -> bool:
    for index in indexes:
        if index["column_names"] != columns:
            continue
        if unique is None or index["unique"] is unique:
            return True
    return False


@pytest.mark.asyncio
async def test_upgrade_from_empty_schema_creates_riot_and_replay_tables(
    test_database_url: str,
) -> None:
    config = _alembic_config(test_database_url)
    try:
        await asyncio.to_thread(command.downgrade, config, "base")
        await asyncio.to_thread(command.upgrade, config, "head")

        tables = await _table_names(test_database_url)
        assert {"players", "recent_match_caches", "matches"}.issubset(tables)
        assert {"replay_uploads", "replay_jobs", "replay_artifacts"}.issubset(tables)
        assert "player_platform_detections" in tables
        assert not {"timelines", "analyses", "scores", "replays"}.intersection(tables)

        replay_upload_columns = await _column_names(test_database_url, "replay_uploads")
        assert "selected_puuid" in replay_upload_columns
        assert "token_digest" in replay_upload_columns

        detection_columns = await _column_names(test_database_url, "player_platform_detections")
        assert {
            "id",
            "game_name_key",
            "tag_line_key",
            "canonical_game_name",
            "canonical_tag_line",
            "puuid",
            "result_status",
            "candidate_platforms",
            "fetched_at",
            "expires_at",
            "confirmation_expires_at",
            "created_at",
            "updated_at",
        }.issubset(detection_columns)
    finally:
        await _restore_head(test_database_url, config)


@pytest.mark.asyncio
async def test_replay_migration_round_trip_preserves_riot_cache_tables(
    test_database_url: str,
) -> None:
    config = _alembic_config(test_database_url)
    try:
        await _restore_head(test_database_url, config)
        await asyncio.to_thread(command.downgrade, config, "0001_phase_2_riot_cache")

        tables_after_downgrade = await _table_names(test_database_url)
        assert {"players", "recent_match_caches", "matches"}.issubset(tables_after_downgrade)
        assert not {"replay_uploads", "replay_jobs", "replay_artifacts"}.intersection(
            tables_after_downgrade
        )
        assert "player_platform_detections" not in tables_after_downgrade

        await asyncio.to_thread(command.upgrade, config, "head")
        tables_after_reupgrade = await _table_names(test_database_url)
        assert {"players", "recent_match_caches", "matches"}.issubset(tables_after_reupgrade)
        assert {"replay_uploads", "replay_jobs", "replay_artifacts"}.issubset(
            tables_after_reupgrade
        )
        assert "player_platform_detections" in tables_after_reupgrade
    finally:
        await _restore_head(test_database_url, config)


@pytest.mark.asyncio
async def test_platform_detection_migration_preserves_players_and_changes_uniqueness(
    test_database_url: str,
) -> None:
    config = _alembic_config(test_database_url)
    engine = create_async_engine(test_database_url)
    try:
        await _truncate_players(test_database_url)
        await asyncio.to_thread(command.downgrade, config, "base")
        await asyncio.to_thread(command.upgrade, config, "0002_replay_r1")

        now = datetime.now(UTC)
        player_ids = (uuid4(), uuid4())
        async with engine.begin() as connection:
            for player_id, puuid, game_name in (
                (player_ids[0], "preserve-puuid-a", "Alpha"),
                (player_ids[1], "preserve-puuid-b", "Beta"),
            ):
                await connection.execute(
                    text(
                        """
                        INSERT INTO players (
                            id, puuid, platform, game_name, tag_line,
                            game_name_key, tag_line_key, summoner_level, profile_icon_id,
                            fetched_at, updated_at
                        ) VALUES (
                            :id, :puuid, 'NA1', :game_name, 'NA1',
                            :game_name_key, 'na1', 10, 1,
                            :fetched_at, :updated_at
                        )
                        """
                    ),
                    {
                        "id": player_id,
                        "puuid": puuid,
                        "game_name": game_name,
                        "game_name_key": game_name.lower(),
                        "fetched_at": now,
                        "updated_at": now,
                    },
                )

        await asyncio.to_thread(command.upgrade, config, "head")

        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text(
                            "SELECT id, puuid, platform, game_name FROM players ORDER BY game_name"
                        )
                    )
                )
                .mappings()
                .all()
            )
        assert len(rows) == 2
        assert [row["puuid"] for row in rows] == ["preserve-puuid-a", "preserve-puuid-b"]
        assert [row["id"] for row in rows] == list(player_ids)

        unique_constraints, indexes = await _player_constraints(test_database_url)
        assert not _has_unique_on(unique_constraints, ["puuid"])
        assert not any(index["unique"] and index["column_names"] == ["puuid"] for index in indexes)
        assert _has_unique_on(unique_constraints, ["platform", "puuid"]) or any(
            index["unique"] and index["column_names"] == ["platform", "puuid"] for index in indexes
        )
        assert _has_index_on(indexes, ["puuid"], unique=False)
        assert _has_index_on(indexes, ["platform"])

        shared_puuid = "shared-across-platforms"
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO players (
                        id, puuid, platform, game_name, tag_line,
                        game_name_key, tag_line_key, summoner_level, profile_icon_id,
                        fetched_at, updated_at
                    ) VALUES
                    (
                        :id_na, :puuid, 'NA1', 'SharedNA', 'NA1',
                        'sharedna', 'na1', 1, 1, :now, :now
                    ),
                    (
                        :id_euw, :puuid, 'EUW1', 'SharedEU', 'EUW',
                        'sharedeu', 'euw', 1, 1, :now, :now
                    )
                    """
                ),
                {
                    "id_na": uuid4(),
                    "id_euw": uuid4(),
                    "puuid": shared_puuid,
                    "now": now,
                },
            )

        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO players (
                            id, puuid, platform, game_name, tag_line,
                            game_name_key, tag_line_key, summoner_level, profile_icon_id,
                            fetched_at, updated_at
                        ) VALUES (
                            :id, :puuid, 'NA1', 'Dup', 'NA1', 'dup', 'na1', 1, 1, :now, :now
                        )
                        """
                    ),
                    {"id": uuid4(), "puuid": shared_puuid, "now": now},
                )
    finally:
        await engine.dispose()
        await _restore_head(test_database_url, config)


@pytest.mark.asyncio
async def test_platform_detection_downgrade_restores_puuid_unique_when_data_allows(
    test_database_url: str,
) -> None:
    config = _alembic_config(test_database_url)
    engine = create_async_engine(test_database_url)
    try:
        await _truncate_players(test_database_url)
        await asyncio.to_thread(command.downgrade, config, "base")
        await asyncio.to_thread(command.upgrade, config, "head")

        now = datetime.now(UTC)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO players (
                        id, puuid, platform, game_name, tag_line,
                        game_name_key, tag_line_key, summoner_level, profile_icon_id,
                        fetched_at, updated_at
                    ) VALUES (
                        :id, 'solo-puuid', 'NA1', 'Solo', 'NA1', 'solo', 'na1', 1, 1, :now, :now
                    )
                    """
                ),
                {"id": uuid4(), "now": now},
            )

        await asyncio.to_thread(command.downgrade, config, "0002_replay_r1")
        tables = await _table_names(test_database_url)
        assert "player_platform_detections" not in tables
        unique_constraints, indexes = await _player_constraints(test_database_url)
        assert _has_unique_on(unique_constraints, ["puuid"]) or any(
            index["unique"] and index["column_names"] == ["puuid"] for index in indexes
        )
        assert not _has_unique_on(unique_constraints, ["platform", "puuid"])
        assert not any(
            index["unique"] and index["column_names"] == ["platform", "puuid"] for index in indexes
        )

        await asyncio.to_thread(command.upgrade, config, "head")
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE TABLE players CASCADE"))
            await connection.execute(
                text(
                    """
                    INSERT INTO players (
                        id, puuid, platform, game_name, tag_line,
                        game_name_key, tag_line_key, summoner_level, profile_icon_id,
                        fetched_at, updated_at
                    ) VALUES
                    (:id_na, 'dup-puuid', 'NA1', 'A', 'NA1', 'a', 'na1', 1, 1, :now, :now),
                    (:id_euw, 'dup-puuid', 'EUW1', 'B', 'EUW', 'b', 'euw', 1, 1, :now, :now)
                    """
                ),
                {"id_na": uuid4(), "id_euw": uuid4(), "now": now},
            )

        with pytest.raises(IntegrityError):
            await asyncio.to_thread(command.downgrade, config, "0002_replay_r1")
    finally:
        await engine.dispose()
        await _restore_head(test_database_url, config)


@pytest.mark.asyncio
async def test_platform_detection_migration_round_trip_on_normal_fixture(
    test_database_url: str,
) -> None:
    config = _alembic_config(test_database_url)
    try:
        await _restore_head(test_database_url, config)
        await asyncio.to_thread(command.downgrade, config, "0002_replay_r1")
        await asyncio.to_thread(command.upgrade, config, "head")

        tables = await _table_names(test_database_url)
        assert "player_platform_detections" in tables
        unique_constraints, indexes = await _player_constraints(test_database_url)
        assert not _has_unique_on(unique_constraints, ["puuid"])
        assert _has_unique_on(unique_constraints, ["platform", "puuid"]) or any(
            index["unique"] and index["column_names"] == ["platform", "puuid"] for index in indexes
        )
        assert _has_index_on(indexes, ["puuid"], unique=False)
        assert _has_index_on(indexes, ["platform"])
    finally:
        await _restore_head(test_database_url, config)


async def _timeline_table_shape(test_database_url: str) -> tuple[set[str], list[str], list[dict]]:
    engine = create_async_engine(test_database_url)
    try:
        async with engine.connect() as connection:

            def reflect(sync_connection):  # type: ignore[no-untyped-def]
                inspector = inspect(sync_connection)
                columns = {column["name"] for column in inspector.get_columns("match_timelines")}
                pk = inspector.get_pk_constraint("match_timelines")["constrained_columns"]
                indexes = inspector.get_indexes("match_timelines")
                return columns, pk, indexes

            return await connection.run_sync(reflect)
    finally:
        await engine.dispose()


async def _count_rows(test_database_url: str, table_name: str) -> int:
    engine = create_async_engine(test_database_url)
    try:
        async with engine.connect() as connection:
            return int(
                (await connection.execute(text(f"SELECT COUNT(*) FROM {table_name}"))).scalar_one()
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_match_timeline_migration_preserves_existing_data_and_shape(
    test_database_url: str,
) -> None:
    config = _alembic_config(test_database_url)
    engine = create_async_engine(test_database_url)
    try:
        await asyncio.to_thread(command.downgrade, config, "base")
        await asyncio.to_thread(command.upgrade, config, "0003_player_platform_detection")

        now = datetime.now(UTC)
        player_id = uuid4()
        replay_id = uuid4()
        job_id = uuid4()
        artifact_id = uuid4()
        detection_id = uuid4()

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO players (
                        id, puuid, platform, game_name, tag_line,
                        game_name_key, tag_line_key, summoner_level, profile_icon_id,
                        fetched_at, updated_at
                    ) VALUES (
                        :id, 'timeline-preserve-puuid', 'NA1', 'Timeline', 'NA1',
                        'timeline', 'na1', 12, 3, :now, :now
                    )
                    """
                ),
                {"id": player_id, "now": now},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO matches (
                        match_id, platform, queue_id, game_version, started_at,
                        duration_seconds, snapshot, schema_version, snapshot_hash, fetched_at
                    ) VALUES (
                        'NA1_timeline_preserve', 'NA1', 420, '16.15.1', :now,
                        1800, '{"ok": true}'::jsonb, 1, :hash, :now
                    )
                    """
                ),
                {"now": now, "hash": "a" * 64},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO player_platform_detections (
                        id, game_name_key, tag_line_key, canonical_game_name, canonical_tag_line,
                        puuid, result_status, candidate_platforms, fetched_at, expires_at,
                        confirmation_expires_at, created_at, updated_at
                    ) VALUES (
                        :id, 'timeline', 'na1', 'Timeline', 'NA1',
                        'timeline-preserve-puuid', 'resolved', '["NA1"]'::jsonb, :now, :expires,
                        NULL, :now, :now
                    )
                    """
                ),
                {"id": detection_id, "now": now, "expires": now},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO replay_uploads (
                        id, match_id, platform, selected_puuid, match_duration_ms, status,
                        progress_percent, token_digest, original_filename, declared_content_type,
                        declared_size_bytes, game_time_zero_ms, rights_statement_version,
                        rights_attested_at, upload_expires_at, warning_codes, created_at,
                        updated_at, version
                    ) VALUES (
                        :id, 'NA1_timeline_preserve', 'NA1', 'timeline-preserve-puuid', 1800000,
                        'created', 0, :digest, 'owned.mp4', 'video/mp4',
                        100, 1000, '2026-08-01', :now, :expires, '[]'::jsonb, :now, :now, 1
                    )
                    """
                ),
                {
                    "id": replay_id,
                    "digest": "b" * 64,
                    "now": now,
                    "expires": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO replay_jobs (
                        id, replay_id, kind, status, attempt_count, max_attempts,
                        available_at, created_at, updated_at
                    ) VALUES (
                        :id, :replay_id, 'process', 'pending', 0, 3, :now, :now, :now
                    )
                    """
                ),
                {"id": job_id, "replay_id": replay_id, "now": now},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO replay_artifacts (
                        id, replay_id, kind, game_time_ms, video_time_ms, object_key,
                        sha256, media_type, size_bytes, width, height, created_at
                    ) VALUES (
                        :id, :replay_id, 'anchor_frame', 0, 1000, 'frames/x',
                        :sha, 'image/jpeg', 10, 1280, 720, :now
                    )
                    """
                ),
                {"id": artifact_id, "replay_id": replay_id, "sha": "c" * 64, "now": now},
            )

        counts_before = {
            "players": await _count_rows(test_database_url, "players"),
            "matches": await _count_rows(test_database_url, "matches"),
            "player_platform_detections": await _count_rows(
                test_database_url, "player_platform_detections"
            ),
            "replay_uploads": await _count_rows(test_database_url, "replay_uploads"),
            "replay_jobs": await _count_rows(test_database_url, "replay_jobs"),
            "replay_artifacts": await _count_rows(test_database_url, "replay_artifacts"),
        }
        assert counts_before == {
            "players": 1,
            "matches": 1,
            "player_platform_detections": 1,
            "replay_uploads": 1,
            "replay_jobs": 1,
            "replay_artifacts": 1,
        }

        await asyncio.to_thread(command.upgrade, config, "head")

        assert await _count_rows(test_database_url, "players") == 1
        assert await _count_rows(test_database_url, "matches") == 1
        assert await _count_rows(test_database_url, "player_platform_detections") == 1
        assert await _count_rows(test_database_url, "replay_uploads") == 1
        assert await _count_rows(test_database_url, "replay_jobs") == 1
        assert await _count_rows(test_database_url, "replay_artifacts") == 1

        tables = await _table_names(test_database_url)
        assert "match_timelines" in tables

        columns, pk, indexes = await _timeline_table_shape(test_database_url)
        assert columns == {
            "platform",
            "match_id",
            "result_status",
            "normalized_snapshot",
            "schema_version",
            "snapshot_hash",
            "fetched_at",
            "expires_at",
            "created_at",
            "updated_at",
        }
        assert pk == ["platform", "match_id"]
        assert _has_index_on(indexes, ["expires_at"], unique=False)
        forbidden = ("raw", "payload", "response", "url", "puuid", "token")
        assert not any(any(token in name.lower() for token in forbidden) for name in columns)

        await asyncio.to_thread(command.downgrade, config, "0003_player_platform_detection")
        tables_after_downgrade = await _table_names(test_database_url)
        assert "match_timelines" not in tables_after_downgrade
        assert "players" in tables_after_downgrade
        assert "matches" in tables_after_downgrade
        assert "player_platform_detections" in tables_after_downgrade
        assert "replay_uploads" in tables_after_downgrade

        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.downgrade, config, "0003_player_platform_detection")
        await asyncio.to_thread(command.upgrade, config, "head")
        assert "match_timelines" in await _table_names(test_database_url)
    finally:
        await engine.dispose()
        await _restore_head(test_database_url, config)


@pytest.mark.asyncio
async def test_match_timeline_database_checks_enforce_result_shapes(
    test_database_url: str,
) -> None:
    config = _alembic_config(test_database_url)
    engine = create_async_engine(test_database_url)
    try:
        await _restore_head(test_database_url, config)
        now = datetime.now(UTC)

        async def insert_row(**values: object) -> None:
            payload = {
                "platform": "NA1",
                "match_id": f"NA1_shape_{uuid4().hex[:8]}",
                "result_status": "available",
                "normalized_snapshot": {"schema_version": 1},
                "schema_version": 1,
                "snapshot_hash": "d" * 64,
                "fetched_at": now,
                "expires_at": now,
                "created_at": now,
                "updated_at": now,
            }
            payload.update(values)
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO match_timelines (
                            platform, match_id, result_status, normalized_snapshot,
                            schema_version, snapshot_hash, fetched_at, expires_at,
                            created_at, updated_at
                        ) VALUES (
                            :platform, :match_id, :result_status,
                            CAST(:normalized_snapshot AS jsonb),
                            :schema_version, :snapshot_hash, :fetched_at, :expires_at,
                            :created_at, :updated_at
                        )
                        """
                    ),
                    {
                        **payload,
                        "normalized_snapshot": None
                        if payload["normalized_snapshot"] is None
                        else '{"schema_version": 1}',
                    },
                )

        await insert_row()
        await insert_row(
            match_id=f"NA1_not_found_{uuid4().hex[:8]}",
            result_status="not_found",
            normalized_snapshot=None,
            snapshot_hash=None,
        )

        with pytest.raises(IntegrityError):
            await insert_row(result_status="weird")
        with pytest.raises(IntegrityError):
            await insert_row(schema_version=0)
        with pytest.raises(IntegrityError):
            await insert_row(normalized_snapshot=None)
        with pytest.raises(IntegrityError):
            await insert_row(snapshot_hash=None)
        with pytest.raises(IntegrityError):
            await insert_row(
                result_status="not_found",
                normalized_snapshot={"schema_version": 1},
                snapshot_hash="e" * 64,
            )
        with pytest.raises(IntegrityError):
            await insert_row(
                result_status="not_found",
                normalized_snapshot=None,
                snapshot_hash="e" * 64,
            )
    finally:
        await engine.dispose()
        await _restore_head(test_database_url, config)
