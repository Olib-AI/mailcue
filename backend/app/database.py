"""Async SQLAlchemy engine, session factory, and declarative base.

Uses ``aiosqlite`` for development (zero-config SQLite) and Psycopg 3 for
asynchronous PostgreSQL access.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import ConnectionPoolEntry

from app.config import settings

_database_backend = make_url(settings.database_url).get_backend_name()
_connect_args: dict[str, object] = {}
_engine_args: dict[str, object] = {}
if _database_backend == "sqlite":
    _connect_args["check_same_thread"] = False
elif _database_backend == "postgresql":
    _engine_args.update(
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_recycle=settings.database_pool_recycle,
    )

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args=_connect_args,
    **_engine_args,
)

if _database_backend == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite_connection(
        dbapi_connection: DBAPIConnection,
        connection_record: ConnectionPoolEntry,
    ) -> None:
        cursor = dbapi_connection.cursor()
        if settings.database_encryption_key:
            escaped_key = settings.database_encryption_key.replace("'", "''")
            cursor.execute(f"PRAGMA key='{escaped_key}'")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a database session.

    The session is automatically closed when the request finishes.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
