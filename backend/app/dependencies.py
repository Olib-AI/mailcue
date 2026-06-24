"""Shared FastAPI dependencies: database session, authentication, authorization."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import APIKey, User
from app.auth.scopes import scope_satisfied
from app.auth.service import validate_api_key
from app.auth.utils import decode_jwt
from app.database import get_db

_bearer_scheme = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    """The resolved principal for a request.

    Interactive sessions (Bearer JWT or refresh cookie) represent the
    human owner and hold every scope over all of their mailboxes. An API
    key holds only the scopes and mailboxes it was granted.
    """

    user: User
    api_key: APIKey | None  # None ⇒ interactive session (full power)

    @property
    def is_api_key(self) -> bool:
        return self.api_key is not None

    @property
    def scopes(self) -> list[str]:
        """Effective scopes (sessions get the wildcard)."""
        return ["*"] if self.api_key is None else list(self.api_key.scopes or [])

    @property
    def allowed_mailboxes(self) -> list[str] | None:
        """Mailbox allow-list (lowercased), or ``None`` for no restriction."""
        if self.api_key is None or not self.api_key.allowed_mailboxes:
            return None
        return [m.lower() for m in self.api_key.allowed_mailboxes]

    def has_scope(self, scope: str) -> bool:
        if self.api_key is None:
            return True
        return scope_satisfied(list(self.api_key.scopes or []), scope)

    def mailbox_allowed(self, address: str) -> bool:
        allowed = self.allowed_mailboxes
        return allowed is None or address.lower() in allowed

    def require_scope(self, scope: str) -> None:
        if not self.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key is missing the required '{scope}' permission",
            )


async def get_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    api_key: str | None = Depends(_api_key_header),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    """Resolve the authenticated principal from a Bearer JWT **or** X-API-Key.

    Raises ``HTTPException(401)`` when neither is provided or both are invalid.
    """
    # --- Path 1: Bearer JWT ---------------------------------------------------
    if credentials is not None:
        user = await _user_from_jwt(credentials.credentials, db)
        return AuthContext(user=user, api_key=None)

    # --- Path 2: API key header -----------------------------------------------
    if api_key is not None:
        resolved = await validate_api_key(api_key, db)
        if resolved is not None:
            user, key = resolved
            return AuthContext(user=user, api_key=key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # --- Path 3: Refresh token cookie (for web UI) ----------------------------
    refresh_cookie = request.cookies.get("refresh_token")
    if refresh_cookie is not None:
        user = await _user_from_jwt(refresh_cookie, db, allow_refresh=True)
        return AuthContext(user=user, api_key=None)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(auth: AuthContext = Depends(get_auth)) -> User:
    """Resolve the authenticated user (without its permission context).

    Kept for endpoints that only need identity. Endpoints that touch a
    specific mailbox or a scoped resource should depend on ``get_auth``
    (and use ``require_scope`` / ``verify_mailbox_access``) instead.
    """
    return auth.user


def require_scope(scope: str) -> Callable[..., Awaitable[AuthContext]]:
    """Build a dependency that enforces *scope* on the request's principal.

    Use in a route's ``dependencies=[...]`` list:

        @router.post("/send", dependencies=[Depends(require_scope("email:send"))])
    """

    async def _dep(auth: AuthContext = Depends(get_auth)) -> AuthContext:
        auth.require_scope(scope)
        return auth

    return _dep


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
