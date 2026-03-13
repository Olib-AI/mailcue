"""Telegram-specific sandbox service helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.sandbox.service import resolve_provider_by_credential

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.sandbox.models import SandboxProvider

logger = logging.getLogger("mailcue.sandbox.telegram")

# Simple in-memory counters keyed by provider_id.
_message_counters: dict[str, int] = {}
_update_counters: dict[str, int] = {}


async def resolve_bot_token(db: AsyncSession, token: str) -> SandboxProvider | None:
    """Resolve a Telegram bot token to a sandbox provider."""
    return await resolve_provider_by_credential(db, "telegram", "bot_token", token)


def get_chat_id(provider: SandboxProvider) -> int:
    """Return a stable chat_id derived from the provider's id."""
    return abs(hash(provider.id)) % (10**9)


def next_message_id(provider_id: str) -> int:
    """Return a monotonically increasing message id per provider."""
    current = _message_counters.get(provider_id, 0) + 1
    _message_counters[provider_id] = current
    return current


def next_update_id(provider_id: str) -> int:
    """Return a monotonically increasing update id per provider."""
    current = _update_counters.get(provider_id, 0) + 1
    _update_counters[provider_id] = current
    return current
