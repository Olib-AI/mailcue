"""Public, token-gated helpers that downstream seeders use to stand
sandbox fixtures up in one round trip.

Every endpoint here is mounted at ``/sandbox/admin/...`` and gated by
a shared-secret token passed via ``X-Mailcue-Sandbox-Admin-Token``.
The token comes from the ``MAILCUE_SANDBOX_ADMIN_TOKEN`` environment
variable; if unset the endpoints respond with 503 so they cannot be
accidentally exposed in a hardened production deployment.

The primary caller today is ``backend/scripts/seed.py`` in the fase
repository — it upserts one :class:`SandboxProvider` per real
phone-provider (twilio / bandwidth / vonage / plivo / telnyx) so the
credentials saved on fase's side authenticate against the Mailcue
emulators.  The endpoint is deliberately idempotent — supply the same
``provider_type`` + ``credentials.account_sid`` / ``auth_id`` twice and
the second call is a no-op.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.database import get_db
from app.sandbox.models import (
    SandboxPhoneNumber,
    SandboxProvider,
    SandboxWebhookEndpoint,
)

logger = logging.getLogger("mailcue.sandbox.admin")

router = APIRouter(prefix="/sandbox/admin", tags=["Sandbox Admin"])


def _admin_token() -> str | None:
    return os.environ.get("MAILCUE_SANDBOX_ADMIN_TOKEN") or None


async def _require_admin_token(
    x_mailcue_sandbox_admin_token: str | None = Header(default=None),
) -> None:
    expected = _admin_token()
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sandbox admin API disabled (MAILCUE_SANDBOX_ADMIN_TOKEN unset).",
        )
    if x_mailcue_sandbox_admin_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid sandbox admin token.",
        )


class SeedProviderSpec(BaseModel):
    """One provider row to upsert."""

    provider_type: str
    name: str
    credentials: dict[str, Any]


class SeedProvidersRequest(BaseModel):
    """Payload for ``POST /sandbox/admin/providers/seed``.

    ``owner_email`` is the e-mail address of the Mailcue ``User``
    that should own every upserted provider — typically the Mailcue
    admin user.  The user must already exist; the endpoint does NOT
    create users to keep the trust boundary minimal.
    """

    owner_email: str
    providers: list[SeedProviderSpec]


class SeedProvidersResponse(BaseModel):
    created: int
    updated: int
    provider_ids: dict[str, str]


def _identity_key(spec: SeedProviderSpec) -> str:
    """Return the stable identity-field value for an upsert.

    ``provider_type`` + this value uniquely identifies a row; used so
    two seed runs with the same inputs don't stack rows.
    """
    creds = spec.credentials
    for key in ("account_sid", "auth_id", "api_key", "account_id"):
        val = creds.get(key)
        if val:
            return str(val)
    return spec.name


@router.post(
    "/providers/seed",
    response_model=SeedProvidersResponse,
    dependencies=[Depends(_require_admin_token)],
)
async def seed_providers(
    body: SeedProvidersRequest,
    db: AsyncSession = Depends(get_db),
) -> SeedProvidersResponse:
    """Idempotently upsert sandbox provider rows."""
    owner_stmt = select(User).where(User.email == body.owner_email)
    owner = (await db.execute(owner_stmt)).scalar_one_or_none()
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mailcue user '{body.owner_email}' not found",
        )

    created = 0
    updated = 0
    ids: dict[str, str] = {}

    for spec in body.providers:
        ident = _identity_key(spec)
        existing_stmt = select(SandboxProvider).where(
            SandboxProvider.user_id == owner.id,
            SandboxProvider.provider_type == spec.provider_type,
        )
        existing_rows = (await db.execute(existing_stmt)).scalars().all()

        # Prefer the row whose credential matches ident.
        match: SandboxProvider | None = None
        for row in existing_rows:
            for key in ("account_sid", "auth_id", "api_key", "account_id"):
                if str(row.credentials.get(key, "")) == ident:
                    match = row
                    break
            if match is not None:
                break

        if match is None:
            row = SandboxProvider(
                user_id=owner.id,
                provider_type=spec.provider_type,
                name=spec.name,
                credentials=spec.credentials,
                is_active=True,
            )
            db.add(row)
            await db.flush()
            created += 1
            ids[f"{spec.provider_type}:{ident}"] = row.id
        else:
            match.name = spec.name
            # Merge credentials — never delete keys that seed didn't set.
            merged = dict(match.credentials or {})
            merged.update(spec.credentials)
            match.credentials = merged
            match.is_active = True
            updated += 1
            ids[f"{spec.provider_type}:{ident}"] = match.id

    await db.commit()
    logger.info(
        "sandbox admin seed: created=%d updated=%d owner=%s",
        created,
        updated,
        body.owner_email,
    )
    return SeedProvidersResponse(created=created, updated=updated, provider_ids=ids)


class SeedWebhookSpec(BaseModel):
    """One webhook endpoint to upsert for a seeded provider."""

    provider_type: str
    url: str
    event_types: list[str] = []
    secret: str | None = None


class SeedWebhooksRequest(BaseModel):
    """Payload for ``POST /sandbox/admin/webhooks/seed``.

    Idempotently registers one :class:`SandboxWebhookEndpoint` per
    ``(provider_type, url)`` pair for the owner user's sandbox
    providers, so that simulate-inbound and message-sent events get
    delivered back to the consumer project (e.g. fase).
    """

    owner_email: str
    webhooks: list[SeedWebhookSpec]


class SeedWebhooksResponse(BaseModel):
    created: int
    updated: int
    endpoint_ids: dict[str, str]


@router.post(
    "/webhooks/seed",
    response_model=SeedWebhooksResponse,
    dependencies=[Depends(_require_admin_token)],
)
async def seed_webhooks(
    body: SeedWebhooksRequest,
    db: AsyncSession = Depends(get_db),
) -> SeedWebhooksResponse:
    """Idempotently register webhook endpoints for seeded providers."""
    from app.sandbox.models import SandboxWebhookEndpoint

    owner_stmt = select(User).where(User.email == body.owner_email)
    owner = (await db.execute(owner_stmt)).scalar_one_or_none()
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mailcue user '{body.owner_email}' not found",
        )

    created = 0
    updated = 0
    ids: dict[str, str] = {}

    for spec in body.webhooks:
        # Find any sandbox provider of this type owned by the user.
        prov_stmt = select(SandboxProvider).where(
            SandboxProvider.user_id == owner.id,
            SandboxProvider.provider_type == spec.provider_type,
        )
        providers = (await db.execute(prov_stmt)).scalars().all()
        if not providers:
            logger.warning(
                "webhook seed skipped: no provider of type %s for %s",
                spec.provider_type,
                body.owner_email,
            )
            continue

        for prov in providers:
            existing_stmt = select(SandboxWebhookEndpoint).where(
                SandboxWebhookEndpoint.provider_id == prov.id,
                SandboxWebhookEndpoint.url == spec.url,
            )
            existing = (await db.execute(existing_stmt)).scalar_one_or_none()
            if existing is None:
                row = SandboxWebhookEndpoint(
                    provider_id=prov.id,
                    url=spec.url,
                    secret=spec.secret,
                    event_types=spec.event_types or [],
                    is_active=True,
                )
                db.add(row)
                await db.flush()
                created += 1
                ids[f"{spec.provider_type}:{spec.url}"] = row.id
            else:
                existing.secret = spec.secret
                existing.event_types = spec.event_types or existing.event_types
                existing.is_active = True
                updated += 1
                ids[f"{spec.provider_type}:{spec.url}"] = existing.id

    await db.commit()
    logger.info(
        "sandbox admin webhook seed: created=%d updated=%d owner=%s",
        created,
        updated,
        body.owner_email,
    )
    return SeedWebhooksResponse(created=created, updated=updated, endpoint_ids=ids)


class ProviderCaInfo(BaseModel):
    subject: str
    sha256_fingerprint: str
    hostnames: list[str]


@router.get("/ca-info", response_model=ProviderCaInfo)
async def provider_ca_info() -> ProviderCaInfo:
    """Return the Mailcue CA subject + fingerprint + issued hostnames.

    Unauthenticated on purpose — the CA public cert is published
    anyway and this endpoint is convenient for diagnostics.
    """
    from pathlib import Path

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    from app.sandbox.scripts.generate_provider_certs import (
        PROVIDER_HOSTNAMES,
        _default_leaves_dir,
    )

    pub_ca = Path(_default_leaves_dir()).parent / "provider_ca.crt"
    if not pub_ca.exists():
        # Fall back to the /etc/ssl/mailcue/ca.crt that init-mailcue makes.
        pub_ca = Path("/etc/ssl/mailcue/ca.crt")
    if not pub_ca.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provider CA has not been generated yet.",
        )
    cert = x509.load_pem_x509_certificate(pub_ca.read_bytes())
    fp = cert.fingerprint(hashes.SHA256()).hex()
    return ProviderCaInfo(
        subject=cert.subject.rfc4514_string(),
        sha256_fingerprint=fp,
        hostnames=list(PROVIDER_HOSTNAMES),
    )


# ── Simulate inbound ─────────────────────────────────────────────────────────


def _external_id_for(provider_type: str) -> str:
    """Generate a provider-native external id for a simulated inbound message.

    Each provider assigns its own identifier format — Twilio's ``SM`` + 32
    hex, Bandwidth's 32-hex, Vonage's UUID, Plivo's UUID, Telnyx's UUID.
    Producing the right shape here means the webhook payloads carry a
    realistic SID rather than ``None`` and the same SID survives across
    subsequent ``build_webhook_payload`` calls (stable across retries and
    signer re-computation).
    """
    hex32 = uuid.uuid4().hex
    if provider_type == "twilio":
        return f"SM{hex32}"
    if provider_type == "bandwidth":
        return hex32
    # vonage, plivo, telnyx all use UUID strings.
    return str(uuid.uuid4())


class SimulateInboundSpec(BaseModel):
    """Payload for ``POST /sandbox/admin/providers/simulate-inbound``.

    Drives the same code path as the authenticated
    ``POST /api/v1/sandbox/providers/{id}/simulate`` endpoint, but resolves
    the provider row from ``(provider_type, owner_email)`` rather than
    requiring a user JWT — suitable for seed scripts and fase's developer
    tooling.

    Carries both ``to_number`` and ``from_number`` separately (real SMS
    webhooks always carry both) so each provider plugin can format the
    event exactly the way its real service would.
    """

    provider_type: str
    owner_email: str
    to_number: str
    from_number: str
    body: str
    media_urls: list[str] | None = None
    content_type: str = "sms"


class SimulateInboundResponse(BaseModel):
    message_id: str
    provider_id: str
    conversation_id: str
    webhook_endpoints_fired: int


@router.post(
    "/providers/simulate-inbound",
    response_model=SimulateInboundResponse,
    dependencies=[Depends(_require_admin_token)],
)
async def simulate_inbound_admin(
    body: SimulateInboundSpec,
    db: AsyncSession = Depends(get_db),
) -> SimulateInboundResponse:
    """Token-gated simulate-inbound: create an inbound ``SandboxMessage``
    and fire webhooks via the existing ``_fire_webhooks`` bridge.

    Resolves the ``SandboxProvider`` by ``(user_id, provider_type)`` and
    picks the most-recently-updated row when multiple are found (a user
    may own several Twilio subaccounts, for instance).  Also looks up the
    matching ``SandboxPhoneNumber`` row for ``to_number`` so event payloads
    that reference the destination number can carry its metadata.
    """
    from app.sandbox.service import (
        _fire_webhooks,
        get_or_create_conversation,
        store_message,
    )

    owner_stmt = select(User).where(User.email == body.owner_email)
    owner = (await db.execute(owner_stmt)).scalar_one_or_none()
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mailcue user '{body.owner_email}' not found",
        )

    prov_stmt = (
        select(SandboxProvider)
        .where(
            SandboxProvider.user_id == owner.id,
            SandboxProvider.provider_type == body.provider_type,
            SandboxProvider.is_active.is_(True),
        )
        .order_by(SandboxProvider.updated_at.desc().nulls_last())
    )
    provider = (await db.execute(prov_stmt)).scalars().first()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No active sandbox provider of type '{body.provider_type}' "
                f"for user '{body.owner_email}'"
            ),
        )

    # Optional phone-number lookup for the destination number — lets
    # plugin payloads (e.g. Bandwidth's ``applicationId``) enrich the event.
    # ``first()`` guards against duplicate ``(provider_id, e164)`` rows that
    # can exist when a seed re-runs or a test re-uses the same E.164.
    pn_stmt = (
        select(SandboxPhoneNumber)
        .where(
            SandboxPhoneNumber.provider_id == provider.id,
            SandboxPhoneNumber.e164 == body.to_number,
            SandboxPhoneNumber.released.is_(False),
        )
        .order_by(SandboxPhoneNumber.created_at.desc())
        .limit(1)
    )
    destination = (await db.execute(pn_stmt)).scalars().first()

    conv = await get_or_create_conversation(
        db,
        provider.id,
        external_id=f"sim-{body.from_number}",
        name=f"Chat with {body.from_number}",
        conv_type="sms" if body.content_type in {"sms", "mms"} else "direct",
    )

    metadata: dict[str, Any] = {
        "to": body.to_number,
        "from": body.from_number,
        "to_number": body.to_number,
        "from_number": body.from_number,
        "media_urls": list(body.media_urls or []),
        "channel": "sms",
        "message_type": "text",
    }
    # Provider-specific enrichment so plugin ``build_webhook_payload``
    # calls find what they need on ``metadata_json`` without re-querying.
    if body.provider_type == "twilio":
        metadata["account_sid"] = provider.credentials.get("account_sid", "")
    elif body.provider_type == "bandwidth":
        metadata["account_id"] = provider.credentials.get("account_id", "")
        if destination is not None:
            app_id = destination.metadata_json.get("messaging_application_id")
            if app_id:
                metadata["application_id"] = app_id
    elif body.provider_type == "plivo":
        metadata["auth_id"] = provider.credentials.get("auth_id", "")

    # Pre-assign a provider-native external_id so plugin
    # ``build_webhook_payload`` calls and ``build_webhook_signer`` calls both
    # reference the same identifier byte-for-byte.  Without this, signed
    # providers (Twilio, Plivo, Telnyx) would emit payloads whose SIDs
    # differ between the wire body and the signature's signing base —
    # fase's validators reject the result as an invalid signature.
    external_id = _external_id_for(body.provider_type)
    msg = await store_message(
        db,
        provider.id,
        direction="inbound",
        sender=body.from_number,
        content=body.body,
        conversation_id=conv.id,
        content_type=body.content_type,
        external_id=external_id,
        metadata=metadata,
    )

    # Count registered endpoints so the caller sees at a glance whether
    # any webhooks will actually fire.
    ep_stmt = select(SandboxWebhookEndpoint).where(
        SandboxWebhookEndpoint.provider_id == provider.id,
        SandboxWebhookEndpoint.is_active.is_(True),
    )
    endpoint_count = len(list((await db.execute(ep_stmt)).scalars().all()))

    _fire_webhooks(msg)

    logger.info(
        "sandbox admin simulate-inbound: provider=%s msg=%s endpoints=%d",
        provider.id,
        msg.id,
        endpoint_count,
    )
    return SimulateInboundResponse(
        message_id=msg.id,
        provider_id=provider.id,
        conversation_id=conv.id,
        webhook_endpoints_fired=endpoint_count,
    )


__all__ = ["router"]
