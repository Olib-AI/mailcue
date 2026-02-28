"""Shared FastAPI dependencies: database session, authentication, authorization."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.service import validate_api_key
from app.auth.utils import decode_jwt
from app.database import get_db

_bearer_scheme = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    api_key: str | None = Depends(_api_key_header),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from a Bearer JWT **or** X-API-Key header.

    Raises ``HTTPException(401)`` when neither is provided or both are invalid.
    """
    # --- Path 1: Bearer JWT ---------------------------------------------------
    if credentials is not None:
        return await _user_from_jwt(credentials.credentials, db)

    # --- Path 2: API key header -----------------------------------------------
    if api_key is not None:
        user = await validate_api_key(api_key, db)
        if user is not None:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # --- Path 3: Refresh token cookie (for web UI) ----------------------------
    refresh_cookie = request.cookies.get("refresh_token")
    if refresh_cookie is not None:
        return await _user_from_jwt(refresh_cookie, db, allow_refresh=True)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _user_from_jwt(
    token: str,
    db: AsyncSession,
    *,
    allow_refresh: bool = False,
) -> User:
    """Decode a JWT and return the corresponding ``User``."""
    try:
        payload = decode_jwt(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    token_type = payload.get("type")
    if token_type not in ("access", "refresh") or (token_type == "refresh" and not allow_refresh):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency that enforces admin privileges on the current user."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user
