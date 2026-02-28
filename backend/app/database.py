"""Async SQLAlchemy engine, session factory, and declarative base.

Uses ``aiosqlite`` for development (zero-config SQLite) and can be switched
to ``asyncpg`` (PostgreSQL) by changing ``MAILCUE_DATABASE_URL``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

_connect_args: dict[str, object] = {}
if settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args=_connect_args,
)

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
