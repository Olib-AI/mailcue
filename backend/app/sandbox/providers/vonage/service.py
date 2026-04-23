"""Vonage credential resolution and helpers."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.sandbox.models import SandboxCall, SandboxPhoneNumber, SandboxProvider
from app.sandbox.service import resolve_provider_by_credential

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_by_api_key(
    db: AsyncSession, api_key: str, api_secret: str
) -> SandboxProvider | None:
    provider = await resolve_provider_by_credential(db, "vonage", "api_key", api_key)
    if provider is None:
        return None
    if provider.credentials.get("api_secret") != api_secret:
        return None
    return provider


async def resolve_messages_bearer(db: AsyncSession, token: str) -> SandboxProvider | None:
    """Resolve a Vonage provider by its Messages API JWT bearer.

    In the real world this JWT is signed by the application's private key with
    the application_id as iss. In the sandbox we short-circuit: any provider
    whose credentials contain the same ``application_id`` or ``messages_token``
    value matches.
    """
    # First check token-as-literal
    provider = await resolve_provider_by_credential(db, "vonage", "messages_token", token)
    if provider is not None:
        return provider
    # Fallback: match application_id inside JWT payload
    payload = _decode_jwt_payload(token)
    if payload is None:
        return None
    app_id = payload.get("application_id") or payload.get("iss")
    if not app_id:
        return None
    return await resolve_provider_by_credential(db, "vonage", "application_id", str(app_id))


def _decode_jwt_payload(token: str) -> dict | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        raw = base64.urlsafe_b64decode(padded.encode())
        import json as _json

        return _json.loads(raw.decode())
    except Exception:
        return None


async def list_owned_numbers(db: AsyncSession, provider_id: str) -> list[SandboxPhoneNumber]:
    stmt = (
        select(SandboxPhoneNumber)
        .where(
            SandboxPhoneNumber.provider_id == provider_id,
            SandboxPhoneNumber.released.is_(False),
        )
        .order_by(SandboxPhoneNumber.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_calls_for(db: AsyncSession, provider_id: str, limit: int = 50) -> list[SandboxCall]:
    stmt = (
        select(SandboxCall)
        .where(SandboxCall.provider_id == provider_id)
        .order_by(SandboxCall.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


__all__ = [
    "list_calls_for",
    "list_owned_numbers",
    "resolve_by_api_key",
    "resolve_messages_bearer",
]
