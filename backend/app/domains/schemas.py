"""Pydantic request / response schemas for the domains module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator

# ── Requests ─────────────────────────────────────────────────────


class DomainCreateRequest(BaseModel):
    """Add a new email domain."""

    name: str
    dkim_selector: str = "mail"

    @field_validator("name")
    @classmethod
    def validate_domain_name(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or len(v) > 253:
            raise ValueError("Domain name must be between 1 and 253 characters")
        if ".." in v or v.startswith(".") or v.endswith("."):
            raise ValueError("Invalid domain name format")
        parts = v.split(".")
        if len(parts) < 2:
            raise ValueError("Domain must have at least two parts (e.g. example.com)")
        for part in parts:
            if not part or len(part) > 63:
                raise ValueError("Each label must be 1-63 characters")
            if not all(c.isalnum() or c == "-" for c in part):
                raise ValueError(
                    "Domain labels may only contain alphanumeric characters and hyphens"
                )
            if part.startswith("-") or part.endswith("-"):
                raise ValueError("Domain labels cannot start or end with a hyphen")
        return v


# ── Responses ────────────────────────────────────────────────────


class DnsRecordInfo(BaseModel):
    """A single DNS record that needs to be configured."""

    record_type: str
    hostname: str
    expected_value: str
    verified: bool
    current_value: str | None = None
    purpose: str


class DomainResponse(BaseModel):
    """Basic domain information."""

    id: int
    name: str
    is_active: bool
    created_at: datetime
    dkim_selector: str
    mx_verified: bool
    spf_verified: bool
    dkim_verified: bool
    dmarc_verified: bool
    last_dns_check: datetime | None
    all_verified: bool

    model_config = {"from_attributes": True}


class DomainDetailResponse(DomainResponse):
    """Extended domain info with DNS records and DKIM public key."""

    dns_records: list[DnsRecordInfo]
    dkim_public_key_txt: str | None = None


class DomainListResponse(BaseModel):
    """List of managed domains."""

    domains: list[DomainResponse]
    total: int


class DnsCheckResponse(BaseModel):
    """Result of a live DNS verification check."""

    mx_verified: bool
    spf_verified: bool
    dkim_verified: bool
    dmarc_verified: bool
    all_verified: bool
    dns_records: list[DnsRecordInfo]
