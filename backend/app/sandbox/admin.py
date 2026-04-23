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
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.database import get_db
from app.sandbox.models import SandboxProvider

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


__all__ = ["router"]
