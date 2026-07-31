import asyncio
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_upgrade_from_empty_schema_creates_only_riot_cache_tables(
    test_database_url: str,
) -> None:
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", test_database_url)
    try:
        await asyncio.to_thread(command.downgrade, config, "base")
        await asyncio.to_thread(command.upgrade, config, "head")

        engine = create_async_engine(test_database_url)
        try:
            async with engine.connect() as connection:
                tables = await connection.run_sync(
                    lambda sync_connection: inspect(sync_connection).get_table_names()
                )
        finally:
            await engine.dispose()
        assert {"players", "recent_match_caches", "matches"}.issubset(tables)
        assert not {"timelines", "analyses", "scores", "replays"}.intersection(tables)
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")
