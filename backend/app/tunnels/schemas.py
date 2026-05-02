"""Pydantic v2 request/response schemas for the tunnels module."""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_NAME_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9._-]+$")


def _validate_pubkey_b64(value: str) -> str:
    """Ensure *value* is a base64 string that decodes to exactly 32 bytes."""
    if not isinstance(value, str) or not value:
        raise ValueError("server_pubkey must be a non-empty base64 string")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"server_pubkey is not valid base64: {exc}") from exc
    if len(raw) != 32:
        raise ValueError(f"server_pubkey must decode to 32 bytes (got {len(raw)}).")
    return value


def _validate_name(value: str) -> str:
    """Validate the human-readable tunnel name."""
    if value != value.strip():
        raise ValueError("name must not have leading or trailing whitespace")
    if not 1 <= len(value) <= 120:
        raise ValueError("name must be between 1 and 120 characters")
    if _NAME_RE.fullmatch(value) is None:
        raise ValueError("name may only contain letters, digits, '.', '_' and '-'.")
    return value


def _validate_host(value: str) -> str:
    """Validate the endpoint host (IP or DNS name)."""
    if not 1 <= len(value) <= 255:
        raise ValueError("endpoint_host must be between 1 and 255 characters")
    if any(ch.isspace() for ch in value):
        raise ValueError("endpoint_host must not contain whitespace")
    return value


# ── Create / Update / Response ────────────────────────────────────


class TunnelCreate(BaseModel):
    """Request body for creating a tunnel."""

    name: str
    endpoint_host: str
    endpoint_port: int = Field(default=7843, ge=1, le=65535)
    server_pubkey: str
    enabled: bool = True
    weight: int = Field(default=1, ge=1, le=1000)
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        return _validate_name(v)

    @field_validator("endpoint_host")
    @classmethod
    def _check_host(cls, v: str) -> str:
        return _validate_host(v)

    @field_validator("server_pubkey")
    @classmethod
    def _check_pubkey(cls, v: str) -> str:
        return _validate_pubkey_b64(v)


class TunnelUpdate(BaseModel):
    """Partial PATCH body for updating a tunnel.  All fields optional."""

    name: str | None = None
    endpoint_host: str | None = None
    endpoint_port: int | None = Field(default=None, ge=1, le=65535)
    server_pubkey: str | None = None
    enabled: bool | None = None
    weight: int | None = Field(default=None, ge=1, le=1000)
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str | None) -> str | None:
        return None if v is None else _validate_name(v)

    @field_validator("endpoint_host")
    @classmethod
    def _check_host(cls, v: str | None) -> str | None:
        return None if v is None else _validate_host(v)

    @field_validator("server_pubkey")
    @classmethod
    def _check_pubkey(cls, v: str | None) -> str | None:
        return None if v is None else _validate_pubkey_b64(v)


class TunnelResponse(BaseModel):
    """Public representation of a tunnel."""

    id: str
    name: str
    endpoint_host: str
    endpoint_port: int
    server_pubkey: str
    enabled: bool
    weight: int
    notes: str | None
    last_checked_at: datetime | None
    last_check_ok: bool | None
    last_check_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TunnelClientIdentityRequest(BaseModel):
    """Request body for upserting the client identity public key."""

    public_key: str

    @field_validator("public_key")
    @classmethod
    def _check_pubkey(cls, v: str) -> str:
        return _validate_pubkey_b64(v)


class TunnelClientIdentityResponse(BaseModel):
    """Public response shape for the client identity endpoint."""

    public_key: str | None
    fingerprint: str | None
    updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class TunnelHealthCheckResponse(BaseModel):
    """Result of a TCP-connect health check against a tunnel edge."""

    tunnel_id: str
    ok: bool
    message: str
    checked_at: datetime


class TunnelReloadConfigResponse(BaseModel):
    """Response from the manual ``write_tunnels_json`` reload endpoint."""

    written: bool
    path: str
    reason: str | None = None
