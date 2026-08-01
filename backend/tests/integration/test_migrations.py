import asyncio
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect
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
        assert not {"timelines", "analyses", "scores", "replays"}.intersection(tables)

        replay_upload_columns = await _column_names(test_database_url, "replay_uploads")
        assert "selected_puuid" in replay_upload_columns
        assert "token_digest" in replay_upload_columns
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")


@pytest.mark.asyncio
async def test_replay_migration_round_trip_preserves_riot_cache_tables(
    test_database_url: str,
) -> None:
    config = _alembic_config(test_database_url)
    try:
        await asyncio.to_thread(command.upgrade, config, "head")
        await asyncio.to_thread(command.downgrade, config, "0001_phase_2_riot_cache")

        tables_after_downgrade = await _table_names(test_database_url)
        assert {"players", "recent_match_caches", "matches"}.issubset(tables_after_downgrade)
        assert not {"replay_uploads", "replay_jobs", "replay_artifacts"}.intersection(
            tables_after_downgrade
        )

        await asyncio.to_thread(command.upgrade, config, "head")
        tables_after_reupgrade = await _table_names(test_database_url)
        assert {"players", "recent_match_caches", "matches"}.issubset(tables_after_reupgrade)
        assert {"replay_uploads", "replay_jobs", "replay_artifacts"}.issubset(
            tables_after_reupgrade
        )
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")
