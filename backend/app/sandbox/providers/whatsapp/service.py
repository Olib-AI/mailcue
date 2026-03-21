"""WhatsApp-specific sandbox service helpers."""

from __future__ import annotations

import base64
import logging
import os
from typing import TYPE_CHECKING

from app.sandbox.service import resolve_provider_by_credential

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.sandbox.models import SandboxProvider

logger = logging.getLogger("mailcue.sandbox.whatsapp")

# Simple in-memory counters keyed by provider_id.
_message_counters: dict[str, int] = {}


async def resolve_access_token(db: AsyncSession, token: str) -> SandboxProvider | None:
    """Resolve a Bearer access token to a sandbox provider."""
    return await resolve_provider_by_credential(db, "whatsapp", "access_token", token)


def get_phone_number_id(provider: SandboxProvider) -> str:
    """Return the phone_number_id from the provider's credentials."""
    return str(provider.credentials.get("phone_number_id", "000000000000000"))


def next_message_id(provider_id: str) -> str:
    """Return a monotonically increasing wamid-style message ID per provider.

    Real WhatsApp message IDs look like ``wamid.HBgLMTIzNDU2Nzg5...``.
    We generate a deterministic base64 suffix from the counter.
    """
    current = _message_counters.get(provider_id, 0) + 1
    _message_counters[provider_id] = current
    raw = f"{provider_id}:{current}:{os.getpid()}".encode()
    suffix = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return f"wamid.{suffix}"
