"""FastAPI application factory with lifespan management.

Creates the MailCue API application, registers routers, middleware,
and exception handlers.  The lifespan context manager handles startup
(database initialisation, admin user creation) and shutdown (engine
disposal).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from app.aliases.models import Alias  # noqa: F401 — imported for table creation
from app.aliases.router import router as aliases_router
from app.auth.router import router as auth_router
from app.auth.service import create_default_admin
from app.config import settings
from app.database import AsyncSessionLocal, Base, engine, get_db
from app.domains.models import Domain  # noqa: F401 — imported for table creation
from app.domains.router import router as domains_router
from app.emails.router import router as emails_router
from app.events.bus import event_bus
from app.events.router import router as events_router
from app.exceptions import register_exception_handlers
from app.forwarding.models import ForwardingRule  # noqa: F401 — imported for table creation
from app.forwarding.router import router as forwarding_router
from app.gpg.models import GpgKey  # noqa: F401 — imported for table creation
from app.gpg.router import router as gpg_router
from app.httpbin.models import (  # noqa: F401 — imported for table creation
    HttpBinBin,
    HttpBinRequest,
)
from app.httpbin.router import catch_all_router as httpbin_catch_all_router
from app.httpbin.router import management_router as httpbin_management_router
from app.mailboxes.models import Mailbox
from app.mailboxes.router import router as mailboxes_router
from app.rate_limit import limiter
from app.sandbox.models import (  # noqa: F401 — imported for table creation
    SandboxConversation,
    SandboxMessage,
    SandboxProvider,
    SandboxWebhookDelivery,
    SandboxWebhookEndpoint,
)
from app.sandbox.router import router as sandbox_router
from app.system.models import (  # noqa: F401 — imported for table creation
    ServerSettings,
    TlsCertificate,
)
from app.system.router import router as system_router

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mailcue")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown hooks.

    Startup:
      1. Create database tables (development convenience -- Alembic is
         the canonical migration tool for production).
      2. Create the default admin user if it does not exist.

    Shutdown:
      1. Dispose the async engine to release connection pool resources.
    """
    # ── Startup ──────────────────────────────────────────────────
    logger.info("MailCue API starting up (domain=%s)", settings.domain)

    # Alembic migrations are run by the s6 init script before uvicorn
    # starts.  ``create_all`` is a safety net that creates any tables
    # not yet covered by migrations (e.g. new models during development).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured.")

    async with AsyncSessionLocal() as session:
        await create_default_admin(session)

    # Ensure the admin mailbox exists in the mailboxes table too.
    # The init script creates the Dovecot user and Maildir, but the
    # API lists mailboxes from SQLite — without this row the frontend
    # shows an empty sidebar.
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        admin_address = f"{settings.admin_user}@{settings.domain}"
        stmt = select(Mailbox).where(Mailbox.address == admin_address)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            session.add(
                Mailbox(
                    address=admin_address,
                    display_name=settings.admin_user,
                    domain=settings.domain,
                )
            )
            await session.commit()
            logger.info("Registered admin mailbox '%s' in database.", admin_address)

    # Restore custom TLS certificates from DB to filesystem (the cert
    # directory is not volume-mounted, so certs are lost on restart).
    async with AsyncSessionLocal() as session:
        from app.system.service import restore_custom_certs

        await restore_custom_certs(session)

    # Register forwarding-rule listener on the event bus so incoming
    # emails are automatically evaluated against active rules.
    from app.forwarding.service import process_incoming_email

    async def _on_email_received(event_type: str, data: dict[str, object]) -> None:
        async with AsyncSessionLocal() as session:
            await process_incoming_email(
                session,
                from_address=str(data.get("from", "")),
                to_address=str(data.get("to", data.get("mailbox", ""))),
                subject=str(data.get("subject", "")),
                mailbox=str(data.get("mailbox", "")),
                uid=str(data.get("uid", "")),
            )

    event_bus.add_listener("email.received", _on_email_received)
    logger.info("Forwarding-rule listener registered on event bus.")

    yield

    # ── Shutdown ─────────────────────────────────────────────────
    await engine.dispose()
    logger.info("MailCue API shut down.")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    app = FastAPI(
        title="MailCue API",
        description="Realistic email testing server REST API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # ── Rate limiting ─────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ── Middleware ────────────────────────────────────────────────
    if settings.is_production and settings.cors_origins == ["*"]:
        logger.warning(
            "Wildcard CORS origins ('*') are configured in production mode. "
            "Set MAILCUE_CORS_ORIGINS to restrict allowed origins."
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ───────────────────────────────────────
    register_exception_handlers(app)

    # ── Routers ──────────────────────────────────────────────────
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(emails_router, prefix="/api/v1")
    app.include_router(mailboxes_router, prefix="/api/v1")
    app.include_router(events_router, prefix="/api/v1")
    app.include_router(gpg_router, prefix="/api/v1")
    app.include_router(domains_router, prefix="/api/v1")
    app.include_router(system_router, prefix="/api/v1")
    app.include_router(forwarding_router, prefix="/api/v1")
    app.include_router(aliases_router, prefix="/api/v1")

    # ── HTTP Bin ──────────────────────────────────────────────────
    app.include_router(httpbin_management_router, prefix="/api/v1")
    app.include_router(httpbin_catch_all_router, prefix="/httpbin")

    # ── Sandbox (management API under /api/v1, provider routes at /sandbox/) ──
    if settings.sandbox_enabled:
        app.include_router(sandbox_router, prefix="/api/v1")
        # Register and mount provider-specific sandbox routes
        from app.sandbox.providers import register_all_providers
        from app.sandbox.registry import get_all_providers

        register_all_providers()
        for _name, provider_plugin in get_all_providers().items():
            app.include_router(provider_plugin.get_router())

    # ── Health check ─────────────────────────────────────────────
    @app.get("/api/v1/health", tags=["Health"])
    async def health_check() -> dict[str, str]:
        """Lightweight health probe for Docker HEALTHCHECK and load balancers."""
        return {"status": "ok", "service": "mailcue-api"}

    # ── MTA-STS policy (RFC 8461) ──────────────────────────────
    # Must be served at /.well-known/mta-sts.txt (root path, no /api prefix)
    @app.get("/.well-known/mta-sts.txt", response_class=PlainTextResponse, tags=["Domains"])
    async def mta_sts_policy_wellknown(
        db: AsyncSession = Depends(get_db),
    ) -> str:
        """Serve MTA-STS policy at the RFC-mandated path."""
        from pathlib import Path

        from app.system.service import get_server_hostname

        hostname = await get_server_hostname(db)

        # Use enforce mode in production when a real TLS cert is configured
        sts_mode = "testing"
        if settings.is_production:
            has_external_cert = bool(settings.tls_cert_path and settings.tls_key_path)
            has_uploaded_cert = Path("/etc/ssl/mailcue/server.crt").exists()
            if has_external_cert or has_uploaded_cert:
                sts_mode = "enforce"

        return f"version: STSv1\nmode: {sts_mode}\nmx: {hostname}\nmax_age: 86400\n"

    return app


app = create_app()
