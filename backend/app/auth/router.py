"""Auth router -- login, 2FA, password change, TOTP management, API keys."""

from __future__ import annotations

import logging

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import APIKey, User
from app.auth.schemas import (
    AdminResetPasswordRequest,
    APIKeyCreatedResponse,
    APIKeyCreateRequest,
    APIKeyResponse,
    ChangePasswordRequest,
    LoginRequest,
    LoginStepResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    TOTPConfirmRequest,
    TOTPDisableRequest,
    TOTPSetupResponse,
    TwoFactorVerifyRequest,
    UserListResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.auth.service import (
    api_key_prefix,
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_api_key,
    generate_totp_qr_base64,
    generate_totp_secret,
    get_totp_provisioning_uri,
    hash_password,
    is_account_locked,
    record_failed_login,
    reset_failed_login,
    verify_password,
    verify_totp_code,
)
from app.auth.utils import (
    create_2fa_temp_token,
    create_access_token,
    create_refresh_token,
    decode_jwt,
)
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.rate_limit import limiter

logger = logging.getLogger("mailcue.auth")

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Login ────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse | LoginStepResponse)
@limiter.limit(settings.login_rate_limit)
async def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse | LoginStepResponse:
    """Authenticate with username + password.

    Returns an access token in the response body and sets the refresh
    token as an ``httpOnly`` cookie for the web UI.

    If the user has TOTP enabled, returns a ``LoginStepResponse`` with
    a short-lived temp token instead; the client must call ``/login/2fa``.
    """
    stmt = select(User).where(User.username == body.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    # Check lockout BEFORE password verification to prevent timing leaks
    # and ensure locked accounts are fully blocked.
    if user is not None and is_account_locked(user):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is temporarily locked due to too many failed login attempts",
        )

    if user is None or not verify_password(body.password, user.hashed_password):
        if user is not None:
            await record_failed_login(user, db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled",
        )

    # If TOTP is enabled, return a temp token for the 2FA step
    if user.totp_enabled:
        await reset_failed_login(user, db)
        temp_token = create_2fa_temp_token(user.id)
        return LoginStepResponse(requires_2fa=True, temp_token=temp_token)

    # No 2FA -- issue full tokens
    await reset_failed_login(user, db)
    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)

    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        samesite="strict" if settings.is_production else "lax",
        secure=settings.is_production,
        max_age=60 * 60 * 24 * 7,  # 7 days
        path="/api/v1/auth/refresh",
    )

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user=UserResponse.model_validate(user, from_attributes=True),
    )


# ── 2FA verification ─────────────────────────────────────────────


@router.post("/login/2fa", response_model=TokenResponse)
@limiter.limit(settings.login_rate_limit)
async def login_2fa(
    request: Request,
    body: TwoFactorVerifyRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Complete login by verifying a TOTP code after step 1."""
    try:
        payload = decode_jwt(body.temp_token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired 2FA token",
        ) from exc

    if payload.get("type") != "2fa_temp":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
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

    if is_account_locked(user):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is temporarily locked due to too many failed attempts",
        )

    if not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP not configured",
        )

    try:
        secret = decrypt_totp_secret(user.totp_secret)
    except InvalidToken:
        logger.warning(
            "TOTP secret for user '%s' cannot be decrypted (secret key changed?). Resetting 2FA.",
            user.username,
        )
        user.totp_enabled = False
        user.totp_secret = None
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP secret could not be decrypted. 2FA has been reset — please set it up again.",
        ) from None
    if not verify_totp_code(secret, body.code):
        await record_failed_login(user, db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid TOTP code",
        )

    await reset_failed_login(user, db)
    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)

    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        samesite="strict" if settings.is_production else "lax",
        secure=settings.is_production,
        max_age=60 * 60 * 24 * 7,
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
@limiter.limit(settings.sensitive_rate_limit)
async def register(
    request: Request,
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
        max_mailboxes=body.max_mailboxes,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("User '%s' created by admin.", body.username)
    return user


# ── Password change ──────────────────────────────────────────────


@router.put("/password")
@limiter.limit(settings.sensitive_rate_limit)
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Change the current user's password."""
    if is_account_locked(current_user):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is temporarily locked due to too many failed attempts",
        )

    if not verify_password(body.current_password, current_user.hashed_password):
        await record_failed_login(current_user, db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    await reset_failed_login(current_user, db)
    current_user.hashed_password = hash_password(body.new_password)
    await db.commit()
    logger.info("Password changed for user '%s'.", current_user.username)
    return {"status": "ok"}


# ── Admin password reset ─────────────────────────────────────────


@router.put("/admin/reset-password")
async def admin_reset_password(
    body: AdminResetPasswordRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Reset a user's password without knowing the old one. **Admin only.**"""
    stmt = select(User).where(User.username == body.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{body.username}' not found",
        )

    user.hashed_password = hash_password(body.new_password)
    await db.commit()
    logger.info("Password reset for user '%s' by admin '%s'.", body.username, _admin.username)
    return {"message": "Password reset successfully"}


# ── TOTP setup / confirm / disable ───────────────────────────────


@router.post("/totp/setup", response_model=TOTPSetupResponse)
async def totp_setup(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TOTPSetupResponse:
    """Generate a TOTP secret and QR code for authenticator setup.

    The secret is stored encrypted but TOTP is **not yet enabled** until
    the user confirms with a valid code via ``POST /totp/confirm``.
    """
    if current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP is already enabled",
        )

    secret = generate_totp_secret()
    provisioning_uri = get_totp_provisioning_uri(secret, current_user.username)
    qr_code = generate_totp_qr_base64(provisioning_uri)

    # Store encrypted secret (not yet enabled)
    current_user.totp_secret = encrypt_totp_secret(secret)
    await db.commit()

    return TOTPSetupResponse(
        secret=secret,
        qr_code=qr_code,
        provisioning_uri=provisioning_uri,
    )


@router.post("/totp/confirm")
@limiter.limit(settings.login_rate_limit)
async def totp_confirm(
    request: Request,
    body: TOTPConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Verify a TOTP code from the authenticator app and enable 2FA."""
    if current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP is already enabled",
        )

    if not current_user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP setup has not been initiated. Call POST /totp/setup first.",
        )

    try:
        secret = decrypt_totp_secret(current_user.totp_secret)
    except InvalidToken:
        current_user.totp_secret = None
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP secret could not be decrypted. Please restart setup with POST /totp/setup.",
        ) from None
    if not verify_totp_code(secret, body.code):
        await record_failed_login(current_user, db)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code. Please try again.",
        )

    await reset_failed_login(current_user, db)
    current_user.totp_enabled = True
    await db.commit()
    logger.info("TOTP 2FA enabled for user '%s'.", current_user.username)
    return {"status": "ok"}


@router.post("/totp/disable")
@limiter.limit(settings.login_rate_limit)
async def totp_disable(
    request: Request,
    body: TOTPDisableRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Disable TOTP 2FA. Requires the current password and a valid TOTP code."""
    if not current_user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP is not enabled",
        )

    if is_account_locked(current_user):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is temporarily locked due to too many failed attempts",
        )

    if not verify_password(body.password, current_user.hashed_password):
        await record_failed_login(current_user, db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password is incorrect",
        )

    if not current_user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP secret not found",
        )

    try:
        secret = decrypt_totp_secret(current_user.totp_secret)
    except InvalidToken:
        logger.warning(
            "TOTP secret for user '%s' cannot be decrypted. Force-disabling 2FA.",
            current_user.username,
        )
        current_user.totp_enabled = False
        current_user.totp_secret = None
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP secret could not be decrypted. 2FA has been force-disabled.",
        ) from None
    if not verify_totp_code(secret, body.code):
        await record_failed_login(current_user, db)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code",
        )

    await reset_failed_login(current_user, db)
    current_user.totp_enabled = False
    current_user.totp_secret = None
    await db.commit()
    logger.info("TOTP 2FA disabled for user '%s'.", current_user.username)
    return {"status": "ok"}


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
        samesite="strict" if settings.is_production else "lax",
        secure=settings.is_production,
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
    stmt = (
        select(APIKey).where(APIKey.user_id == current_user.id).order_by(APIKey.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def revoke_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke an API key by removing it permanently."""
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

    name = api_key.name
    await db.delete(api_key)
    await db.commit()
    logger.info("API key '%s' removed by user '%s'.", name, current_user.username)


# ── User management (admin) ────────────────────────────────────


@router.get("/users", response_model=UserListResponse)
async def list_users(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    """List all users. **Admin only.**"""
    stmt = select(User).order_by(User.created_at.desc())
    result = await db.execute(stmt)
    users = list(result.scalars().all())
    return UserListResponse(
        users=[UserResponse.model_validate(u, from_attributes=True) for u in users],
        total=len(users),
    )


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update a user's admin-editable fields. **Admin only.**"""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Prevent admin from removing their own admin role
    if body.is_admin is False and user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove your own admin privileges",
        )

    if body.max_mailboxes is not None:
        user.max_mailboxes = body.max_mailboxes
    if body.is_active is not None:
        if not body.is_active and user.id == admin.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate your own account",
            )
        user.is_active = body.is_active
    if body.is_admin is not None:
        user.is_admin = body.is_admin

    await db.commit()
    await db.refresh(user)
    logger.info("User '%s' updated by admin '%s'.", user.username, admin.username)
    return UserResponse.model_validate(user, from_attributes=True)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def deactivate_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Deactivate a user account. **Admin only.**

    The user's mailboxes are preserved but become orphaned.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    user.is_active = False
    await db.commit()
    logger.info("User '%s' deactivated by admin '%s'.", user.username, admin.username)
