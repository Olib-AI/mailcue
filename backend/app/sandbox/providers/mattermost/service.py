"""Mattermost-specific sandbox service helpers."""

from __future__ import annotations

import logging
import random
import string
from typing import TYPE_CHECKING

from app.sandbox.service import resolve_provider_by_credential

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.sandbox.models import SandboxProvider

logger = logging.getLogger("mailcue.sandbox.mattermost")


async def resolve_access_token(db: AsyncSession, token: str) -> SandboxProvider | None:
    """Resolve a Mattermost access token to a sandbox provider."""
    return await resolve_provider_by_credential(db, "mattermost", "access_token", token)


def generate_post_id() -> str:
    """Generate a 26-character alphanumeric ID (Mattermost style)."""
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=26))
