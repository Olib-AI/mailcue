"""Alembic migration environment -- configured for async SQLAlchemy.

Uses ``render_as_batch=True`` for SQLite compatibility (ALTER TABLE
limitations).  Reads the database URL from ``app.config.settings`` so
the single source of truth is the ``MAILCUE_DATABASE_URL`` env var.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import create_engine, event, pool

from alembic import context

# Import all models so their metadata is registered on ``Base``.
from app.auth.models import APIKey, User  # noqa: F401
from app.config import settings
from app.database import Base
from app.domains.models import Domain  # noqa: F401
from app.mailboxes.models import Mailbox  # noqa: F401
from app.system.models import ServerSettings, TlsCertificate  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Convert the async URL to a synchronous one for Alembic CLI usage.
# ``sqlite+aiosqlite:///...`` → ``sqlite:///...``
db_url = settings.database_url.replace("+aiosqlite", "")
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode -- emits SQL to stdout."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode -- connected to the database."""
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url", ""),
        poolclass=pool.NullPool,
    )

    if settings.database_encryption_key:

        @event.listens_for(connectable, "connect")
        def _set_sqlcipher_key(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute(f"PRAGMA key='{settings.database_encryption_key}'")
            cursor.close()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
