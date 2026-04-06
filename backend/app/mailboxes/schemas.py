"""Pydantic schemas for the mailbox management module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator


class MailboxCreateRequest(BaseModel):
    """Request body for creating a new mailbox.

    The full address is composed as ``username@domain``.  If ``domain``
    is omitted, the server's ``MAILCUE_DOMAIN`` setting is used.
    """

    username: str
    password: str
    domain: str | None = None
    display_name: str = ""

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 4:
            raise ValueError("Password must be at least 4 characters")
        return v


class MailboxResponse(BaseModel):
    """Public mailbox representation."""

    id: str
    address: str
    username: str = ""
    display_name: str
    domain: str
    is_active: bool
    created_at: datetime
    quota_mb: int = 500
    email_count: int = 0
    unread_count: int = 0
    junk_count: int = 0
    signature: str = ""
    owner_id: str | None = None

    model_config = {"from_attributes": True}


class MailboxListResponse(BaseModel):
    """Wrapper for the mailbox listing endpoint."""

    mailboxes: list[MailboxResponse]
    total: int


class MailboxStats(BaseModel):
    """Mailbox statistics returned from IMAP STATUS."""

    mailbox_id: str
    address: str
    total_emails: int
    unread_emails: int
    total_size_bytes: int
    folders: list[FolderInfo]

    model_config = {"from_attributes": True}


class FolderInfo(BaseModel):
    """Per-folder message counts."""

    name: str
    message_count: int
    unseen_count: int


class DisplayNameUpdateRequest(BaseModel):
    """Request body for updating a mailbox display name."""

    display_name: str


class SignatureUpdateRequest(BaseModel):
    """Request body for updating a mailbox signature."""

    signature: str = ""


# Rebuild MailboxStats now that FolderInfo is defined
MailboxStats.model_rebuild()
