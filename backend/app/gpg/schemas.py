"""GPG Pydantic request / response schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SignatureStatus(str, Enum):
    """Result of a PGP signature verification."""

    valid = "valid"
    invalid = "invalid"
    no_public_key = "no_public_key"
    expired_key = "expired_key"
    error = "error"


class GenerateKeyRequest(BaseModel):
    """Request body for generating a new GPG keypair."""

    mailbox_address: str
    name: str = "MailCue User"
    algorithm: str = Field(default="RSA", pattern="^(RSA|ECC)$")
    key_length: int = Field(default=2048, ge=1024, le=4096)
    expire: str | None = None  # e.g. "1y", "6m", "0" for no expiration


class ImportKeyRequest(BaseModel):
    """Request body for importing an armored PGP key."""

    armored_key: str
    mailbox_address: str | None = None  # override auto-detected address


class GpgKeyResponse(BaseModel):
    """Serialised GPG key metadata returned by the API."""

    id: str
    mailbox_address: str
    fingerprint: str
    key_id: str
    uid_name: str | None = None
    uid_email: str | None = None
    algorithm: str | None = None
    key_length: int | None = None
    created_at: datetime
    expires_at: datetime | None = None
    is_private: bool
    is_active: bool

    model_config = {"from_attributes": True}


class GpgKeyListResponse(BaseModel):
    """Paginated list of GPG keys."""

    keys: list[GpgKeyResponse]
    total: int


class GpgKeyExportResponse(BaseModel):
    """Armored PGP public key export."""

    mailbox_address: str
    fingerprint: str
    public_key: str  # armored PGP public key


class GpgEmailInfo(BaseModel):
    """PGP/MIME metadata attached to a parsed email."""

    is_signed: bool = False
    is_encrypted: bool = False
    signature_status: SignatureStatus | None = None
    signer_fingerprint: str | None = None
    signer_key_id: str | None = None
    signer_uid: str | None = None
    decrypted: bool = False
    encryption_key_ids: list[str] = Field(default_factory=list)
