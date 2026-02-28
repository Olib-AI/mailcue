"""JWT encode / decode helpers.

Separated from ``service.py`` to keep the service layer free of direct
``python-jose`` coupling -- makes testing and future migration to PyJWT
straightforward.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from app.config import settings


def encode_jwt(payload: dict[str, Any]) -> str:
    """Encode *payload* into a signed JWT string."""
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_jwt(token: str) -> dict[str, Any]:
    """Decode and verify a JWT string.

    Raises:
        ValueError: If the token is invalid, expired, or the signature does
            not match.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc


def create_access_token(user_id: str) -> str:
    """Build a short-lived access JWT for *user_id*."""
    expire = datetime.now(UTC) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return encode_jwt({"sub": user_id, "type": "access", "exp": expire})


def create_refresh_token(user_id: str) -> str:
    """Build a long-lived refresh JWT for *user_id*."""
    expire = datetime.now(UTC) + timedelta(
        days=settings.refresh_token_expire_days
    )
    return encode_jwt({"sub": user_id, "type": "refresh", "exp": expire})
