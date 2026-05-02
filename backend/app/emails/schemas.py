"""Pydantic request / response schemas for the email module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.gpg.schemas import GpgEmailInfo


class AttachmentInfo(BaseModel):
    """Metadata about a single MIME attachment."""

    filename: str
    content_type: str
    size: int
    part_id: str


class EmailSummary(BaseModel):
    """Lightweight representation used in list views."""

    uid: str
    mailbox: str
    from_address: str
    from_name: str = ""
    to_addresses: list[str]
    subject: str
    date: datetime | None = None
    has_attachments: bool
    is_read: bool
    preview: str
    message_id: str = ""
    in_reply_to: str | None = None
    references: list[str] = []
    thread_id: str = ""
    size: int = 0
    is_signed: bool = False
    is_encrypted: bool = False


class EmailDetail(EmailSummary):
    """Full representation including body and headers."""

    html_body: str | None = None
    text_body: str | None = None
    cc_addresses: list[str] = []
    bcc_addresses: list[str] = []
    raw_headers: dict[str, str] = {}
    attachments: list[AttachmentInfo] = []
    gpg: GpgEmailInfo | None = None


class EmailListResponse(BaseModel):
    """Paginated list of email summaries."""

    total: int
    page: int
    page_size: int
    emails: list[EmailSummary]
    has_more: bool = False


class SendAttachment(BaseModel):
    """Base64-encoded file attachment for outgoing emails."""

    filename: str
    content_type: str
    data: str  # base64-encoded content


class SendEmailRequest(BaseModel):
    """Send a new email via SMTP."""

    from_address: str
    from_name: str = ""
    to_addresses: list[str]
    cc_addresses: list[str] = []
    subject: str
    body: str = ""
    body_type: str = "plain"
    attachments: list[SendAttachment] = []
    sign: bool = False
    encrypt: bool = False
    reply_to: str | None = None
    in_reply_to: str | None = None
    references: list[str] = []
    # When true, attach `List-Unsubscribe` + `List-Unsubscribe-Post`
    # headers (RFC 8058 one-click). Only set on actual bulk / list mail
    # — Gmail and other receivers treat its presence on transactional
    # 1:1 mail as a "this is a marketing list" signal and bias toward
    # spam-folder. Default False so the API and the web Compose UI
    # produce clean transactional messages out of the box.
    bulk: bool = False
    list_unsubscribe: str | None = None
    list_unsubscribe_post: str | None = None


class InjectEmailRequest(BaseModel):
    """Inject an email directly into a mailbox via IMAP APPEND."""

    mailbox: str
    from_address: str
    to_addresses: list[str]
    subject: str
    html_body: str | None = None
    text_body: str | None = None
    date: datetime | None = None
    headers: dict[str, str] = {}
    sign: bool = False
    encrypt: bool = False
    reply_to: str | None = None
    in_reply_to: str | None = None
    references: list[str] = []
    cc_addresses: list[str] = []
    return_path: str | None = None
    realistic_headers: bool = True


class BulkInjectRequest(BaseModel):
    """Inject multiple emails at once."""

    emails: list[InjectEmailRequest]


class BulkInjectResponse(BaseModel):
    """Result of a bulk inject operation."""

    injected: int
    failed: int
    ids: list[str]


class UpdateFlagsRequest(BaseModel):
    """Update IMAP flags on an email (e.g. mark as read/unread)."""

    seen: bool


class BulkDeleteRequest(BaseModel):
    """Delete multiple emails from a mailbox."""

    uids: list[str]


class BulkDeleteResponse(BaseModel):
    """Result of a bulk delete operation."""

    deleted: int
    failed: int


class SpamActionRequest(BaseModel):
    """Request body for spam / not-spam actions (source folder)."""

    folder: str = "INBOX"
