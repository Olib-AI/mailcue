"""Discord-specific sandbox service helpers."""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

from app.sandbox.service import resolve_provider_by_credential

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.sandbox.models import SandboxProvider

logger = logging.getLogger("mailcue.sandbox.discord")

# Simple in-memory counters keyed by provider_id for snowflake generation.
_snowflake_counters: dict[str, int] = {}

# Discord epoch: 2015-01-01T00:00:00Z in milliseconds
_DISCORD_EPOCH = 1_420_070_400_000


async def resolve_bot_token(db: AsyncSession, token: str) -> SandboxProvider | None:
    """Resolve a Bot token to a sandbox provider."""
    return await resolve_provider_by_credential(db, "discord", "bot_token", token)


def next_snowflake(provider_id: str) -> str:
    """Generate a Discord snowflake-style ID.

    Discord snowflakes encode a timestamp, worker/process info, and an
    incrementing sequence.  We produce deterministic, monotonically increasing
    IDs scoped per provider.
    """
    current = _snowflake_counters.get(provider_id, 0) + 1
    _snowflake_counters[provider_id] = current

    timestamp_ms = int(time.time() * 1000) - _DISCORD_EPOCH
    worker_id = os.getpid() % 32
    # snowflake layout: timestamp (42 bits) | worker (5 bits) | process (5 bits) | increment (12 bits)
    snowflake = (timestamp_ms << 22) | (worker_id << 17) | (worker_id << 12) | (current % 4096)
    return str(snowflake)


def get_application_id(provider: SandboxProvider) -> str:
    """Return the application_id from the provider's credentials."""
    return str(provider.credentials.get("application_id", "000000000000000000"))


def get_bot_user(provider: SandboxProvider) -> dict[str, Any]:
    """Return a Discord User object representing the bot."""
    app_id = get_application_id(provider)
    return {
        "id": app_id,
        "username": provider.name,
        "discriminator": "0000",
        "avatar": None,
        "bot": True,
        "system": False,
        "mfa_enabled": False,
        "verified": True,
        "flags": 0,
        "public_flags": 0,
    }
