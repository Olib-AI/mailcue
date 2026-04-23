"""Plivo credential resolution helpers."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from app.sandbox.models import SandboxProvider
from app.sandbox.service import resolve_provider_by_credential

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def extract_basic_auth(authorization: str | None) -> tuple[str, str] | None:
    if not authorization or not authorization.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(authorization.removeprefix("Basic ").strip()).decode()
        user, _, pw = decoded.partition(":")
        if not user:
            return None
        return user, pw
    except Exception:
        return None


async def resolve_account(
    db: AsyncSession, auth_id: str, auth_token: str
) -> SandboxProvider | None:
    provider = await resolve_provider_by_credential(db, "plivo", "auth_id", auth_id)
    if provider is None:
        return None
    if provider.credentials.get("auth_token") != auth_token:
        return None
    return provider


__all__ = ["extract_basic_auth", "resolve_account"]
