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
