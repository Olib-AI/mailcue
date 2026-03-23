"""Pydantic request / response schemas for the aliases module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator


class AliasCreateRequest(BaseModel):
    """Create a new email alias."""

    source_address: str
    destination_address: str

    @field_validator("source_address")
    @classmethod
    def validate_source(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("Source address must not be empty")
        if "@" not in v:
            raise ValueError("Source address must contain '@'")
        return v

    @field_validator("destination_address")
    @classmethod
    def validate_destination(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or "@" not in v:
            raise ValueError("Destination address must be a valid email")
        return v


class AliasUpdateRequest(BaseModel):
    """Update an existing alias."""

    destination_address: str | None = None
    enabled: bool | None = None

    @field_validator("destination_address")
    @classmethod
    def validate_destination(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if not v or "@" not in v:
            raise ValueError("Destination address must be a valid email")
        return v


class AliasResponse(BaseModel):
    """Public alias representation."""

    id: int
    source_address: str
    destination_address: str
    domain: str
    is_catchall: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AliasListResponse(BaseModel):
    """Wrapper for the alias listing endpoint."""

    aliases: list[AliasResponse]
    total: int
