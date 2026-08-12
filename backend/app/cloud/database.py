from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import CloudSettings


@dataclass(slots=True)
class CloudDatabase:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]

    @classmethod
    def create(cls, settings: CloudSettings) -> "CloudDatabase":
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_recycle=900,
        )
        return cls(
            engine=engine,
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
        )

    async def close(self) -> None:
        await self.engine.dispose()

    async def healthcheck(self) -> bool:
        async with self.engine.connect() as connection:
            return bool(await connection.scalar(text("select true")))

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session


async def set_tenant_context(session: AsyncSession, workspace_id: int) -> None:
    if workspace_id <= 0:
        raise ValueError("workspace_id 必须是正整数")
    await session.execute(
        text("select set_config('app.current_workspace_id', :workspace_id, true)"),
        {"workspace_id": str(workspace_id)},
    )


@asynccontextmanager
async def tenant_transaction(
    session: AsyncSession,
    workspace_id: int,
) -> AsyncIterator[AsyncSession]:
    async with session.begin():
        await set_tenant_context(session, workspace_id)
        yield session
