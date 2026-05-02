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

from fastapi import Depends, FastAPI, Request
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
from app.domains.models import Domain
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
from app.sandbox.admin import router as sandbox_admin_router
from app.sandbox.models import (  # noqa: F401 — imported for table creation
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
from app.sandbox.router import router as sandbox_router
from app.system.models import (  # noqa: F401 — imported for table creation
    ServerSettings,
    TlsCertificate,
)
from app.system.router import router as system_router
from app.tunnels.models import (  # noqa: F401 — imported for table creation
    Tunnel,
    TunnelClientIdentity,
)
from app.tunnels.router import router as tunnels_router

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
    # shows an empty sidebar. Always link it to the default admin user
    # so the multi-user owner filter (introduced in migration 012)
    # surfaces the mailbox in `/mailboxes` and the compose dropdown.
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        from app.auth.models import User

        admin_address = f"{settings.admin_user}@{settings.domain}"
        admin_user_row = (
            await session.execute(
                select(User).where(User.username == settings.admin_user, User.is_admin == True)  # noqa: E712
            )
        ).scalar_one_or_none()
        admin_user_id = admin_user_row.id if admin_user_row is not None else None

        stmt = select(Mailbox).where(Mailbox.address == admin_address)
        existing_mailbox = (await session.execute(stmt)).scalar_one_or_none()
        if existing_mailbox is None:
            session.add(
                Mailbox(
                    address=admin_address,
                    display_name=settings.admin_user,
                    domain=settings.domain,
                    user_id=admin_user_id,
                )
            )
            await session.commit()
            logger.info(
                "Registered admin mailbox '%s' (owner=%s) in database.",
                admin_address,
                admin_user_id,
            )
        elif existing_mailbox.user_id is None and admin_user_id is not None:
            # Backfill orphans created before migration 012 / before this
            # owner-link fix landed.
            existing_mailbox.user_id = admin_user_id
            await session.commit()
            logger.info(
                "Backfilled owner of admin mailbox '%s' to user %s.",
                admin_address,
                admin_user_id,
            )

    # Ensure the primary domain is registered in the domains table.
    # The init script configures Postfix/Dovecot with MAILCUE_DOMAIN,
    # but the domains table is what the UI and DNS verification use.
    if settings.is_production:
        async with AsyncSessionLocal() as session:
            from app.domains.service import add_domain

            stmt = select(Domain).where(Domain.name == settings.domain)
            result = await session.execute(stmt)
            existing_domain = result.scalar_one_or_none()
            if existing_domain is None:
                try:
                    await add_domain(settings.domain, "mail", session)
                    logger.info(
                        "Registered primary domain '%s' in database.",
                        settings.domain,
                    )
                except Exception:
                    logger.warning(
                        "Could not auto-register domain '%s' (may already exist).",
                        settings.domain,
                    )
            elif existing_domain.dkim_public_key_txt and (
                "IN\tTXT" in existing_domain.dkim_public_key_txt
                or '" "' in existing_domain.dkim_public_key_txt
            ):
                # Clean up raw opendkim-genkey format stored from before
                # the parser fix.
                raw = existing_domain.dkim_public_key_txt
                txt_part = raw.split("(", 1)[-1].rsplit(")", 1)[0]
                txt_part = txt_part.replace('"', "").replace("\t", " ")
                txt_part = " ".join(txt_part.split())
                existing_domain.dkim_public_key_txt = txt_part.strip()
                await session.commit()
                logger.info("Cleaned up DKIM public key for '%s'.", settings.domain)

    # Restore custom TLS certificates from DB to filesystem (the cert
    # directory is not volume-mounted, so certs are lost on restart).
    async with AsyncSessionLocal() as session:
        from app.system.service import restore_custom_certs

        await restore_custom_certs(session)

    # Render tunnels.json for the relay sidecar.  When the sidecar is
    # not deployed the configured directory is missing -- write_tunnels_json
    # logs a warning and returns without raising, so startup never fails.
    async with AsyncSessionLocal() as session:
        from app.tunnels.service import write_tunnels_json

        try:
            await write_tunnels_json(session)
        except Exception:
            logger.exception("Failed to write tunnels.json during startup.")

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
    app.include_router(tunnels_router, prefix="/api/v1")

    # ── HTTP Bin ──────────────────────────────────────────────────
    app.include_router(httpbin_management_router, prefix="/api/v1")
    app.include_router(httpbin_catch_all_router, prefix="/httpbin")

    # ── Sandbox (management API under /api/v1, provider routes at /sandbox/) ──
    if settings.sandbox_enabled:
        app.include_router(sandbox_router, prefix="/api/v1")
        # Admin-scope helpers (CA info + idempotent provider seeding).
        # Gated by MAILCUE_SANDBOX_ADMIN_TOKEN; see app.sandbox.admin.
        app.include_router(sandbox_admin_router)
        # Register and mount provider-specific sandbox routes
        from app.sandbox.capabilities import router as sandbox_capabilities_router
        from app.sandbox.providers import register_all_providers
        from app.sandbox.registry import get_all_providers

        app.include_router(sandbox_capabilities_router)

        register_all_providers()
        for _name, provider_plugin in get_all_providers().items():
            app.include_router(provider_plugin.get_router())

        # Public CA distribution — fase's image build curl's this at
        # build-time to pin the CA fingerprint into the trust store.
        from fastapi.responses import FileResponse, PlainTextResponse

        @app.get("/sandbox/provider_ca.crt", include_in_schema=False)
        async def _provider_ca_file() -> FileResponse:
            from pathlib import Path

            from fastapi import HTTPException

            from app.sandbox.scripts.generate_provider_certs import (
                _default_leaves_dir,
            )

            ca_pub = Path(_default_leaves_dir()).parent / "provider_ca.crt"
            if not ca_pub.exists():
                ca_pub = Path("/etc/ssl/mailcue/ca.crt")
            if not ca_pub.exists():
                raise HTTPException(
                    status_code=503,
                    detail="Provider CA not yet generated.",
                )
            return FileResponse(
                ca_pub,
                media_type="application/x-x509-ca-cert",
                filename="mailcue-provider-ca.crt",
            )

        @app.get("/sandbox/provider_ca_fingerprint.txt", include_in_schema=False)
        async def _provider_ca_fp() -> PlainTextResponse:
            from pathlib import Path

            from cryptography import x509
            from cryptography.hazmat.primitives import hashes

            from app.sandbox.scripts.generate_provider_certs import (
                _default_leaves_dir,
            )

            fp_file = Path(_default_leaves_dir()).parent / "provider_ca_fingerprint.txt"
            if fp_file.exists():
                return PlainTextResponse(fp_file.read_text(encoding="utf-8"))
            # Compute on the fly from /etc/ssl/mailcue/ca.crt.
            ca = Path("/etc/ssl/mailcue/ca.crt")
            cert = x509.load_pem_x509_certificate(ca.read_bytes())
            return PlainTextResponse(cert.fingerprint(hashes.SHA256()).hex() + "\n")

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

    # ── OpenClaw Skill (dynamic) ─────────────────────────────────
    @app.get(
        "/api/v1/integrations/openclaw/skill",
        response_class=PlainTextResponse,
        tags=["Integrations"],
    )
    async def openclaw_skill(request: Request) -> str:
        """Dynamically generated OpenClaw SKILL.md for this MailCue instance."""
        base_url = str(request.base_url).rstrip("/")
        domain = settings.domain

        return f'''---
name: mailcue
description: "MailCue email operations for {domain}: send, receive, reply, forward, delete, search emails. Use when sending/reading/replying to emails, searching mailbox, or managing aliases."
metadata: {{"openclaw": {{"emoji": "📧", "requires": {{"env": ["MAILCUE_API_KEY"]}}}}}}
---

# MailCue Email Skill — {domain}

Interact with MailCue at `{base_url}` for the domain `{domain}`.

## Setup

Set the API key environment variable:

```bash
export MAILCUE_API_KEY="mc_..."
```

Create an API key at `{base_url}/profile` under **API Keys**, or via the API:

```bash
TOKEN=$(curl -s -X POST {base_url}/api/v1/auth/login \\
  -H "Content-Type: application/json" \\
  -d \'{{"username":"admin","password":"yourpassword"}}\' | jq -r .access_token)

API_KEY=$(curl -s -X POST {base_url}/api/v1/auth/api-keys \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d \'{{"name":"openclaw"}}\' | jq -r .key)
```

## Authentication

All requests use: `X-API-Key: $MAILCUE_API_KEY`

---

## Send an email

```bash
curl -s -X POST {base_url}/api/v1/emails/send \\
  -H "X-API-Key: $MAILCUE_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d \'{{
    "from_address": "user@{domain}",
    "from_name": "Display Name",
    "to_addresses": ["recipient@example.com"],
    "cc_addresses": [],
    "bcc_addresses": [],
    "subject": "Subject line",
    "body": "<p>HTML body</p>",
    "body_type": "html"
  }}\'
```

## Reply to an email

First read the original email, then send with threading headers:

```bash
ORIGINAL=$(curl -s "{base_url}/api/v1/mailboxes/user@{domain}/emails/{{uid}}" \\
  -H "X-API-Key: $MAILCUE_API_KEY")

curl -s -X POST {base_url}/api/v1/emails/send \\
  -H "X-API-Key: $MAILCUE_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d \'{{
    "from_address": "user@{domain}",
    "to_addresses": ["original-sender@example.com"],
    "subject": "Re: Original Subject",
    "body": "<p>Reply content</p>",
    "body_type": "html",
    "in_reply_to": "<message-id-from-original>",
    "references": ["<message-id-from-original>"]
  }}\'
```

Key threading fields:
- `in_reply_to` — the `message_id` of the email being replied to
- `references` — array of ancestor `message_id` values + the parent\'s ID
- Prefix subject with `Re: ` for replies, `Fwd: ` for forwards

## List emails

```bash
curl -s "{base_url}/api/v1/mailboxes/user@{domain}/emails?folder=INBOX&page_size=20" \\
  -H "X-API-Key: $MAILCUE_API_KEY"
```

Parameters: `folder` (INBOX/Sent/Trash/Spam), `search` (text search), `page`, `page_size`

## Read an email

```bash
curl -s "{base_url}/api/v1/mailboxes/user@{domain}/emails/{{uid}}" \\
  -H "X-API-Key: $MAILCUE_API_KEY"
```

Returns: `html_body`, `text_body`, `from_name`, `from_address`, `to_addresses`, `subject`, `date`, `attachments[]`, `message_id`, `raw_headers`

## Forward an email

Read the original, then send to a new recipient with `Fwd: ` subject prefix and the original body included.

## Delete an email

```bash
curl -s -X DELETE "{base_url}/api/v1/mailboxes/user@{domain}/emails/{{uid}}" \\
  -H "X-API-Key: $MAILCUE_API_KEY"
```

First delete moves to Trash. Deleting from Trash permanently removes it.

## Mark as read / unread

```bash
curl -s -X PATCH "{base_url}/api/v1/mailboxes/user@{domain}/emails/{{uid}}/flags" \\
  -H "X-API-Key: $MAILCUE_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d \'{{"seen": true}}\'
```

Set `seen` to `false` to mark as unread.

## Search emails

```bash
curl -s "{base_url}/api/v1/mailboxes/user@{domain}/emails?search=meeting" \\
  -H "X-API-Key: $MAILCUE_API_KEY"
```

Search is scoped to the specified folder (default: INBOX).

## List mailboxes

```bash
curl -s "{base_url}/api/v1/mailboxes" \\
  -H "X-API-Key: $MAILCUE_API_KEY"
```

## List aliases (admin)

```bash
curl -s "{base_url}/api/v1/aliases" \\
  -H "X-API-Key: $MAILCUE_API_KEY"
```

## Create alias (admin)

```bash
curl -s -X POST "{base_url}/api/v1/aliases" \\
  -H "X-API-Key: $MAILCUE_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d \'{{"source_address": "info@{domain}", "destination_address": "admin@{domain}", "domain": "{domain}"}}\'
```

## Download attachment

```bash
curl -s "{base_url}/api/v1/mailboxes/user@{domain}/emails/{{uid}}/attachments/{{part_id}}" \\
  -H "X-API-Key: $MAILCUE_API_KEY" -o file.pdf
```

## Health check

```bash
curl -s {base_url}/api/v1/health
```

## Tips

- Always use `body_type: "html"` for rich emails — a text/plain fallback is auto-generated
- Threading requires `in_reply_to` and `references` — without these, replies appear as new conversations
- Emails are identified by `uid` within a mailbox
- Admin API keys can access all mailboxes; regular keys access only the owner\'s mailbox
'''

    return app


app = create_app()
