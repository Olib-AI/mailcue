"""Pydantic v2 response models for the MailCue API.

Field names mirror the server's JSON envelope exactly. Every model has
``extra='allow'`` so server-side additions don't break older SDK
versions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SignatureStatus = Literal["valid", "invalid", "no_public_key", "expired_key", "error"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class AttachmentInfo(_Base):
    """Metadata describing one MIME part on a received email."""

    filename: str
    content_type: str
    size: int
    part_id: str


class GpgEmailInfo(_Base):
    """PGP/MIME metadata attached to a parsed email."""

    is_signed: bool = False
    is_encrypted: bool = False
    signature_status: Optional[SignatureStatus] = None
    signer_fingerprint: Optional[str] = None
    signer_key_id: Optional[str] = None
    signer_uid: Optional[str] = None
    decrypted: bool = False
    encryption_key_ids: List[str] = Field(default_factory=list)


class EmailSummary(_Base):
    """Lightweight email representation used in list views."""

    uid: str
    mailbox: str
    from_address: str
    from_name: str = ""
    to_addresses: List[str]
    subject: str
    date: Optional[datetime] = None
    has_attachments: bool
    is_read: bool
    preview: str
    message_id: str = ""
    in_reply_to: Optional[str] = None
    references: List[str] = Field(default_factory=list)
    thread_id: str = ""
    size: int = 0
    is_signed: bool = False
    is_encrypted: bool = False


class EmailDetail(EmailSummary):
    """Full email representation including bodies, headers, attachments."""

    html_body: Optional[str] = None
    text_body: Optional[str] = None
    cc_addresses: List[str] = Field(default_factory=list)
    bcc_addresses: List[str] = Field(default_factory=list)
    raw_headers: Dict[str, str] = Field(default_factory=dict)
    attachments: List[AttachmentInfo] = Field(default_factory=list)
    gpg: Optional[GpgEmailInfo] = None


class EmailListResponse(_Base):
    """Paginated list of email summaries."""

    total: int
    page: int
    page_size: int
    emails: List[EmailSummary]
    has_more: bool = False


class SendResult(_Base):
    """Server response from ``POST /emails/send``."""

    message_id: Optional[str] = None
    status: Optional[str] = None


class FolderInfo(_Base):
    """Per-folder message counts."""

    name: str
    message_count: int
    unseen_count: int


class MailboxStats(_Base):
    """Mailbox statistics returned from IMAP STATUS."""

    mailbox_id: str
    address: str
    total_emails: int
    unread_emails: int
    total_size_bytes: int
    folders: List[FolderInfo]


class Mailbox(_Base):
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


class MailboxListResponse(_Base):
    mailboxes: List[Mailbox]
    total: int


class DnsRecordInfo(_Base):
    record_type: str
    hostname: str
    expected_value: str
    verified: bool
    current_value: Optional[str] = None
    purpose: str


class Domain(_Base):
    """Public domain representation."""

    id: int
    name: str
    is_active: bool
    created_at: datetime
    dkim_selector: str
    mx_verified: bool
    spf_verified: bool
    dkim_verified: bool
    dmarc_verified: bool
    mta_sts_verified: bool
    tls_rpt_verified: bool
    last_dns_check: Optional[datetime] = None
    all_verified: bool


class DomainDetail(Domain):
    dns_records: List[DnsRecordInfo] = Field(default_factory=list)
    dkim_public_key_txt: Optional[str] = None


class DomainListResponse(_Base):
    domains: List[Domain]
    total: int


class DnsCheckResponse(_Base):
    mx_verified: bool
    spf_verified: bool
    dkim_verified: bool
    dmarc_verified: bool
    mta_sts_verified: bool = False
    tls_rpt_verified: bool = False
    all_verified: bool
    dns_records: List[DnsRecordInfo]


class Alias(_Base):
    id: int
    source_address: str
    destination_address: str
    domain: str
    is_catchall: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AliasListResponse(_Base):
    aliases: List[Alias]
    total: int


class GpgKey(_Base):
    id: str
    mailbox_address: str
    fingerprint: str
    key_id: str
    uid_name: Optional[str] = None
    uid_email: Optional[str] = None
    algorithm: Optional[str] = None
    key_length: Optional[int] = None
    created_at: datetime
    expires_at: Optional[datetime] = None
    is_private: bool
    is_active: bool


class GpgKeyListResponse(_Base):
    keys: List[GpgKey]
    total: int


class GpgKeyExport(_Base):
    mailbox_address: str
    fingerprint: str
    public_key: str


class KeyserverPublishResult(_Base):
    published: bool
    key_fingerprint: str
    message: str


class ApiKey(_Base):
    """API key metadata (no raw key)."""

    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    is_active: bool


class CreatedApiKey(ApiKey):
    """Returned only at creation; includes the raw key once."""

    key: str


class BulkInjectResponse(_Base):
    injected: int
    failed: int
    ids: List[str]


class TlsCertificateStatus(_Base):
    configured: bool
    common_name: Optional[str] = None
    san_dns_names: List[str] = Field(default_factory=list)
    not_before: Optional[str] = None
    not_after: Optional[str] = None
    fingerprint_sha256: Optional[str] = None
    uploaded_at: Optional[str] = None


class HealthResponse(_Base):
    """Health-check payload. Schema is intentionally permissive."""

    status: Optional[str] = None


class Event(_Base):
    """Single event emitted by ``GET /events/stream``."""

    event_type: str
    data: Dict[str, Any] = Field(default_factory=dict)
    id: Optional[str] = None
    retry: Optional[int] = None
