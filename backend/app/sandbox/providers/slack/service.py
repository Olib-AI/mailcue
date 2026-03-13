"""Slack-specific sandbox service helpers."""

from __future__ import annotations

import logging
import random
import string
import time
from typing import TYPE_CHECKING

from app.sandbox.service import resolve_provider_by_credential

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.sandbox.models import SandboxProvider

logger = logging.getLogger("mailcue.sandbox.slack")


async def resolve_bot_token(db: AsyncSession, token: str) -> SandboxProvider | None:
    """Resolve a Slack bot token to a sandbox provider."""
    return await resolve_provider_by_credential(db, "slack", "bot_token", token)


def generate_ts() -> str:
    """Generate a Slack-style timestamp string (epoch.microseconds)."""
    now = time.time()
    return f"{int(now)}.{int((now % 1) * 1_000_000):06d}"


def generate_channel_id() -> str:
    """Generate a Slack-style channel ID: C + 10 uppercase alphanumeric chars."""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=10))
    return f"C{suffix}"
