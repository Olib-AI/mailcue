"""Auth business logic -- password hashing, API-key generation, TOTP 2FA, lockout."""

from __future__ import annotations

import base64
import io
import logging
import secrets
from datetime import UTC, datetime, timedelta

import pyotp
import qrcode  # type: ignore[import-untyped]
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
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


# ── TOTP / 2FA helpers ───────────────────────────────────────────


def _get_fernet() -> Fernet:
    """Derive a Fernet key from the application secret using HKDF."""
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"mailcue-totp-encryption",
        info=b"totp-secret-key",
    )
    key = base64.urlsafe_b64encode(kdf.derive(settings.secret_key.encode()))
    return Fernet(key)


def encrypt_totp_secret(secret: str) -> str:
    """Encrypt a TOTP base32 secret for database storage."""
    return _get_fernet().encrypt(secret.encode()).decode()


def decrypt_totp_secret(encrypted: str) -> str:
    """Decrypt a TOTP base32 secret from database storage.

    Raises ``InvalidToken`` (re-exported from cryptography.fernet) when the
    secret cannot be decrypted, typically because the application secret key
    has changed since the TOTP secret was stored.
    """
    return _get_fernet().decrypt(encrypted.encode()).decode()


def generate_totp_secret() -> str:
    """Generate a new random TOTP base32 secret."""
    return pyotp.random_base32()


def get_totp_provisioning_uri(secret: str, username: str) -> str:
    """Build an otpauth:// URI for authenticator app setup."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=settings.totp_issuer)


def generate_totp_qr_base64(provisioning_uri: str) -> str:
    """Generate a QR code as a base64-encoded PNG data URI."""
    img = qrcode.make(provisioning_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


def verify_totp_code(secret: str, code: str) -> bool:
    """Verify a TOTP code with a 1-step drift window."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


# ── Account lockout helpers ──────────────────────────────────────


def is_account_locked(user: User) -> bool:
    """Check whether the user account is currently locked out."""
    if user.locked_until is None:
        return False
    now = datetime.now(UTC)
    if user.locked_until.tzinfo is None:
        # Treat naive datetime as UTC for safety

        locked = user.locked_until.replace(tzinfo=UTC)
    else:
        locked = user.locked_until
    return now < locked


async def record_failed_login(user: User, db: AsyncSession) -> None:
    """Increment failed attempts; lock the account if threshold is reached."""
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= settings.max_failed_login_attempts:
        user.locked_until = datetime.now(UTC) + timedelta(
            minutes=settings.lockout_duration_minutes
        )
        logger.warning(
            "Account '%s' locked for %d minutes after %d failed attempts.",
            user.username,
            settings.lockout_duration_minutes,
            user.failed_login_attempts,
        )
    await db.commit()


async def reset_failed_login(user: User, db: AsyncSession) -> None:
    """Reset failed login counter after a successful login."""
    if user.failed_login_attempts > 0 or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None
        await db.commit()


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
