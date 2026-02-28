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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.auth.service import create_default_admin
from app.config import settings
from app.database import AsyncSessionLocal, Base, engine
from app.emails.router import router as emails_router
from app.events.router import router as events_router
from app.exceptions import register_exception_handlers
from app.gpg.models import GpgKey  # noqa: F401 — imported for table creation
from app.gpg.router import router as gpg_router
from app.mailboxes.models import Mailbox
from app.mailboxes.router import router as mailboxes_router

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
            session.add(Mailbox(
                address=admin_address,
                display_name=settings.admin_user,
                domain=settings.domain,
            ))
            await session.commit()
            logger.info("Registered admin mailbox '%s' in database.", admin_address)

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

    # ── Middleware ────────────────────────────────────────────────
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

    # ── Health check ─────────────────────────────────────────────
    @app.get("/api/v1/health", tags=["Health"])
    async def health_check() -> dict[str, str]:
        """Lightweight health probe for Docker HEALTHCHECK and load balancers."""
        return {"status": "ok", "service": "mailcue-api"}

    return app


app = create_app()
