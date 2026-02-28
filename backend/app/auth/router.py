"""Auth router -- login, register, refresh, API key management."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import APIKey, User
from app.auth.schemas import (
    APIKeyCreatedResponse,
    APIKeyCreateRequest,
    APIKeyResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.auth.service import (
    api_key_prefix,
    generate_api_key,
    hash_password,
    verify_password,
)
from app.auth.utils import create_access_token, create_refresh_token, decode_jwt
from app.database import get_db
from app.dependencies import get_current_user, require_admin

logger = logging.getLogger("mailcue.auth")

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Login ────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate with username + password.

    Returns an access token in the response body and sets the refresh
    token as an ``httpOnly`` cookie for the web UI.
    """
    stmt = select(User).where(User.username == body.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled",
        )

    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)

    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        samesite="lax",
        secure=False,  # Set True behind HTTPS in production
        max_age=60 * 60 * 24 * 7,  # 7 days
        path="/api/v1/auth/refresh",
    )

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user=UserResponse.model_validate(user, from_attributes=True),
    )


# ── Register ─────────────────────────────────────────────────────


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Create a new user account. **Admin only.**"""
    # Check uniqueness
    stmt = select(User).where((User.username == body.username) | (User.email == body.email))
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists",
        )

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        is_admin=body.is_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("User '%s' created by admin.", body.username)
    return user


# ── Current user info ────────────────────────────────────────────


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the currently authenticated user's profile."""
    return UserResponse.model_validate(current_user, from_attributes=True)


# ── Logout ───────────────────────────────────────────────────────


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    """Clear the httpOnly refresh_token cookie."""
    response.delete_cookie("refresh_token", httponly=True, samesite="lax")
    return {"status": "ok"}


# ── Refresh ──────────────────────────────────────────────────────


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    body: RefreshRequest | None = None,
    response: Response = Response(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a refresh token for a new access + refresh token pair.

    The refresh token can be passed in the JSON body **or** read from
    the ``refresh_token`` httpOnly cookie.
    """
    token: str | None = body.refresh_token if body and body.refresh_token else None
    if token is None:
        token = request.cookies.get("refresh_token")
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required",
        )

    try:
        payload = decode_jwt(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from exc

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is not a refresh token",
        )

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad token")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    access = create_access_token(user.id)
    new_refresh = create_refresh_token(user.id)

    response.set_cookie(
        key="refresh_token",
        value=new_refresh,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24 * 7,
        path="/api/v1/auth/refresh",
    )

    return TokenResponse(
        access_token=access,
        refresh_token=new_refresh,
        user=UserResponse.model_validate(user, from_attributes=True),
    )


# ── API Keys ─────────────────────────────────────────────────────


@router.post(
    "/api-keys",
    response_model=APIKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    body: APIKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> APIKeyCreatedResponse:
    """Generate a new API key for the current user.

    The raw key value is returned **only once** in this response.
    """
    raw_key = generate_api_key()
    prefix = api_key_prefix(raw_key)

    api_key = APIKey(
        user_id=current_user.id,
        key_hash=hash_password(raw_key),
        name=body.name,
        prefix=prefix,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info("API key '%s' created for user '%s'.", body.name, current_user.username)

    return APIKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        prefix=api_key.prefix,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        is_active=api_key.is_active,
        key=raw_key,
    )


@router.get("/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[APIKey]:
    """List all API keys for the current user (without raw key values)."""
    stmt = select(APIKey).where(APIKey.user_id == current_user.id).order_by(APIKey.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke (deactivate) an API key."""
    stmt = select(APIKey).where(
        APIKey.id == key_id,
        APIKey.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )

    api_key.is_active = False
    await db.commit()
    logger.info("API key '%s' revoked by user '%s'.", api_key.name, current_user.username)
