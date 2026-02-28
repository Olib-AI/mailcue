"""Pydantic request / response schemas for the auth module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator

# ── Requests ─────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    """Credentials for username + password login."""

    username: str
    password: str


class RegisterRequest(BaseModel):
    """Create a new user (admin only)."""

    username: str
    email: str
    password: str
    is_admin: bool = False

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class APIKeyCreateRequest(BaseModel):
    """Create a new API key for the current user."""

    name: str


class RefreshRequest(BaseModel):
    """Explicitly pass a refresh token (alternative to cookie)."""

    refresh_token: str


# ── Responses ────────────────────────────────────────────────────


class UserResponse(BaseModel):
    """Public user representation."""

    id: str
    username: str
    email: str
    is_admin: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """JWT access + refresh token pair, including the authenticated user."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class APIKeyResponse(BaseModel):
    """Returned once on creation (``key`` field) and on listing (without ``key``)."""

    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class APIKeyCreatedResponse(APIKeyResponse):
    """Extends ``APIKeyResponse`` with the raw key -- returned only at creation time."""

    key: str
