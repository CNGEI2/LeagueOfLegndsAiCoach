from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class DatabaseProtocol(Protocol):
    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class Database:
    def __init__(self, database_url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)

    async def ping(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self._engine.dispose()
