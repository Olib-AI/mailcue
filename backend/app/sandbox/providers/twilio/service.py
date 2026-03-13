"""Twilio-specific sandbox service helpers."""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

from app.sandbox.service import resolve_provider_by_credential

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.sandbox.models import SandboxProvider

logger = logging.getLogger("mailcue.sandbox.twilio")


async def resolve_account(
    db: AsyncSession, account_sid: str, auth_token: str
) -> SandboxProvider | None:
    """Resolve a Twilio account by matching both account_sid and auth_token."""
    provider = await resolve_provider_by_credential(db, "twilio", "account_sid", account_sid)
    if provider is None:
        return None
    if provider.credentials.get("auth_token") != auth_token:
        return None
    return provider


def extract_basic_auth(authorization: str | None) -> tuple[str, str] | None:
    """Extract username and password from a Basic auth header.

    Returns ``(username, password)`` or ``None`` if the header is absent
    or malformed.
    """
    if not authorization or not authorization.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(authorization.removeprefix("Basic ").strip()).decode()
        username, _, password = decoded.partition(":")
        if not username:
            return None
        return username, password
    except Exception:
        return None
