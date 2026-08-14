"""Alembic migration environment -- configured for async SQLAlchemy.

Uses ``render_as_batch=True`` for SQLite compatibility (ALTER TABLE
limitations).  Reads the database URL from ``app.config.settings`` so
the single source of truth is the ``MAILCUE_DATABASE_URL`` env var.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import create_engine, event, pool, text
from sqlalchemy.engine import make_url

from alembic import context
from app.aliases.models import Alias  # noqa: F401

# Import all models so their metadata is registered on ``Base``.
from app.auth.models import APIKey, User  # noqa: F401
from app.config import settings
from app.database import Base
from app.deliverability.models import DeliverabilityReportRecord  # noqa: F401
from app.domains.models import Domain  # noqa: F401
from app.forwarding.models import ForwardingRule  # noqa: F401
from app.gpg.models import GpgKey  # noqa: F401
from app.httpbin.models import HttpBinBin, HttpBinRequest  # noqa: F401
from app.mailboxes.models import Mailbox  # noqa: F401
from app.sandbox.models import (  # noqa: F401
    SandboxBrand,
    SandboxCall,
    SandboxCampaign,
    SandboxConversation,
    SandboxMessage,
    SandboxNumberOrder,
    SandboxPhoneNumber,
    SandboxPortRequest,
    SandboxProvider,
    SandboxWebhookDelivery,
    SandboxWebhookEndpoint,
)
from app.system.models import ServerSettings, TlsCertificate  # noqa: F401
from app.tunnels.models import Tunnel, TunnelClientIdentity  # noqa: F401
from app.warmup.models import (  # noqa: F401
    WarmupAccount,
    WarmupCampaign,
    WarmupCampaignAccount,
    WarmupEvent,
    WarmupProviderState,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Convert async-only drivers to their synchronous migration counterparts.
db_url = make_url(settings.database_url)
if db_url.drivername == "sqlite+aiosqlite":
    db_url = db_url.set(drivername="sqlite")
elif db_url.drivername == "postgresql+asyncpg":
    db_url = db_url.set(drivername="postgresql+psycopg")
# ConfigParser treats percent-encoded credentials as interpolation tokens.
config.set_main_option(
    "sqlalchemy.url",
    db_url.render_as_string(hide_password=False).replace("%", "%%"),
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode -- emits SQL to stdout."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=db_url.get_backend_name() == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode -- connected to the database."""
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url", ""),
        poolclass=pool.NullPool,
    )

    if db_url.get_backend_name() == "sqlite" and settings.database_encryption_key:

        @event.listens_for(connectable, "connect")
        def _set_sqlcipher_key(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute(f"PRAGMA key='{settings.database_encryption_key}'")
            cursor.close()

    with connectable.connect() as connection:
        is_postgres = connection.dialect.name == "postgresql"
        if is_postgres:
            # Runtime queries use a defensive timeout, but schema/index builds
            # must be allowed to finish while holding the migration lock.
            connection.execute(text("SET statement_timeout = 0"))
            connection.execute(text("SELECT pg_advisory_lock(hashtext('mailcue_alembic'))"))
            # The lock is session-scoped, so commit the implicit transaction
            # before Alembic starts its own transactional DDL boundary.
            connection.commit()
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=connection.dialect.name == "sqlite",
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            if is_postgres:
                connection.execute(text("SELECT pg_advisory_unlock(hashtext('mailcue_alembic'))"))
                connection.commit()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
