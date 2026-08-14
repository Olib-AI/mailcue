"""Pydantic request / response schemas for the email module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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


class DeliverabilityEvidence(BaseModel):
    """Structured observation suitable for collapsed UI and API consumers."""

    code: str
    title: str
    value: str | float | int | bool | None = None
    score: float | None = None
    description: str | None = None
    recommendation: str | None = None


class DeliverabilityCheck(BaseModel):
    """One stable, actionable check in a deliverability report."""

    id: str
    category: Literal[
        "authentication",
        "content",
        "headers",
        "transport",
        "spam_filter",
        "attachments",
        "dns",
        "reputation",
        "links",
        "visual",
        "placement",
        "client_previews",
        "ai_analysis",
    ]
    title: str
    status: Literal["pass", "warning", "fail", "info"]
    summary: str
    details: list[str] = Field(default_factory=list)
    evidence: list[DeliverabilityEvidence] = Field(default_factory=list)
    recommendation: str | None = None
    points: float = 0
    max_points: float = 0


class DeliverabilityCategory(BaseModel):
    """Score and check rollup for one report category."""

    id: Literal[
        "authentication",
        "content",
        "headers",
        "transport",
        "spam_filter",
        "attachments",
        "dns",
        "reputation",
        "links",
        "visual",
        "placement",
        "client_previews",
        "ai_analysis",
    ]
    title: str
    score: int | None
    points: float
    max_points: float
    checks: list[DeliverabilityCheck]


class DeliverabilityReport(BaseModel):
    """Versioned deliverability assessment for a received message."""

    score_version: str = "2.2"
    report_id: str | None = None
    raw_sha256: str = ""
    cached: bool = False
    is_baseline: bool = False
    score: int
    verdict: Literal["excellent", "good", "needs_work", "poor"]
    summary: str
    mailbox: str
    uid: str
    folder: str
    message_id: str
    sender_domain: str | None = None
    generated_at: datetime
    categories: list[DeliverabilityCategory]
    top_recommendations: list[str]
    limitations: list[str]


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
    bcc_addresses: list[str] = []
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


class EmailValidationRequest(BaseModel):
    """Request body for email address validation."""

    email: str = Field(min_length=1, max_length=320)


class EmailValidationSyntax(BaseModel):
    """Result of syntax format check."""

    is_valid: bool
    local_part: str | None = None
    domain: str | None = None
    error: str | None = None


class EmailValidationDns(BaseModel):
    """Result of DNS domain MX/NS records checks."""

    is_valid: bool
    has_mx: bool
    has_ns: bool
    has_a: bool
    has_aaaa: bool = False
    null_mx: bool = False
    mx_records: list[str] = []
    ns_records: list[str] = []
    a_records: list[str] = []
    aaaa_records: list[str] = []
    status: Literal["valid", "invalid", "undetermined"] = "invalid"
    error_code: str | None = None
    error: str | None = None


class EmailValidationMailbox(BaseModel):
    """Result of SMTP probe check."""

    is_valid: bool | None = None
    smtp_code: int | None = None
    smtp_response: str | None = None
    catch_all: bool | None = None
    transport: Literal["direct", "mailcue_tunnel", "none"] = "none"
    reason_code: str | None = None
    error: str | None = None


class EmailValidationDisposable(BaseModel):
    """Result of temporary/disposable domain check."""

    is_disposable: bool
    is_forwarding_alias: bool = False
    error: str | None = None


class EmailValidationResponse(BaseModel):
    """Full detailed response of the email validation."""

    email: str
    is_valid: bool
    status: Literal["valid", "invalid", "undetermined", "disposable", "catch_all"]
    verdict: Literal["deliverable", "undeliverable", "risky", "unknown"]
    deliverable: bool | None
    confidence: float
    reason: str
    syntax: EmailValidationSyntax
    dns: EmailValidationDns
    mailbox: EmailValidationMailbox
    disposable: EmailValidationDisposable
