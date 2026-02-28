"""Auth business logic -- password hashing, API-key generation, default admin creation."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import APIKey, User
from app.config import settings

logger = logging.getLogger("mailcue.auth")

_ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)


# ── Password helpers ─────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Return an Argon2id hash of *plain*."""
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return ``True`` when *plain* matches *hashed*."""
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False


def password_needs_rehash(hashed: str) -> bool:
    """Check whether the stored hash should be upgraded to current parameters."""
    return _ph.check_needs_rehash(hashed)


# ── API-key helpers ──────────────────────────────────────────────


def generate_api_key() -> str:
    """Generate a cryptographically secure API key.

    Format: ``mc_<44-char-urlsafe-base64>``  (total ~47 chars).
    """
    return f"mc_{secrets.token_urlsafe(32)}"


def api_key_prefix(raw_key: str) -> str:
    """Extract the first 8 characters for fast DB lookup."""
    return raw_key[:8]


async def validate_api_key(raw_key: str, db: AsyncSession) -> User | None:
    """Look up a raw API key, verify its hash, and return the owning user.

    Returns ``None`` when the key is invalid or inactive.
    """
    prefix = api_key_prefix(raw_key)
    stmt = select(APIKey).where(APIKey.prefix == prefix, APIKey.is_active.is_(True))
    result = await db.execute(stmt)

    for api_key_row in result.scalars():
        if verify_password(raw_key, api_key_row.key_hash):
            # Touch last_used_at
            api_key_row.last_used_at = datetime.now(UTC)
            await db.commit()

            user = await db.get(User, api_key_row.user_id)
            if user is not None and user.is_active:
                return user
    return None


# ── Bootstrap ────────────────────────────────────────────────────


async def create_default_admin(db: AsyncSession) -> None:
    """Ensure the default admin account exists at startup.

    Uses ``MAILCUE_ADMIN_USER`` / ``MAILCUE_ADMIN_PASSWORD`` from the
    environment.  The password is hashed with Argon2id before storage.
    """
    stmt = select(User).where(User.username == settings.admin_user)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        logger.info("Default admin user '%s' already exists.", settings.admin_user)
        return

    admin = User(
        username=settings.admin_user,
        email=f"{settings.admin_user}@{settings.domain}",
        hashed_password=hash_password(settings.admin_password),
        is_admin=True,
        is_active=True,
    )
    db.add(admin)
    await db.commit()
    logger.info("Created default admin user '%s'.", settings.admin_user)
