from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel


class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(
            url, connect_args={"timeout": 30} if url.startswith("sqlite") else {}
        )
        self.sessions = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )
        if url.startswith("sqlite"):

            @event.listens_for(self.engine.sync_engine, "connect")
            def sqlite_pragmas(connection, _):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()

    async def init(self):
        from app.db import models  # noqa: F401

        async with self.engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)

    @asynccontextmanager
    async def transaction(self):
        async with self.sessions() as session:
            try:
                if self.engine.dialect.name == "sqlite":
                    await session.execute(text("BEGIN IMMEDIATE"))
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def close(self):
        await self.engine.dispose()
