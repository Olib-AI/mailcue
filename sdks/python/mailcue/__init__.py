"""MailCue Python SDK.

Drop-in client for the MailCue REST API. Both ``Mailcue`` (sync) and
``AsyncMailcue`` (async) clients expose the same resource surface:
``emails``, ``mailboxes``, ``domains``, ``aliases``, ``gpg``,
``api_keys``, ``system``, and the SSE ``events`` stream.

Example:
    >>> from mailcue import Mailcue
    >>> client = Mailcue(api_key="mc_...")
    >>> client.emails.send(
    ...     from_="hello@example.com",
    ...     to=["user@example.com"],
    ...     subject="Welcome",
    ...     html="<h1>Hi</h1>",
    ... )
"""

from __future__ import annotations

from mailcue._version import __version__
from mailcue.client import AsyncMailcue, Mailcue
from mailcue.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    MailcueError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TimeoutError,
    ValidationError,
)
from mailcue.transport import DEFAULT_BASE_URL
from mailcue.types import (
    Alias,
    AliasListResponse,
    ApiKey,
    AttachmentInfo,
    BulkInjectResponse,
    CreatedApiKey,
    DnsCheckResponse,
    DnsRecordInfo,
    Domain,
    DomainDetail,
    DomainListResponse,
    EmailDetail,
    EmailListResponse,
    EmailSummary,
    Event,
    FolderInfo,
    GpgEmailInfo,
    GpgKey,
    GpgKeyExport,
    GpgKeyListResponse,
    HealthResponse,
    KeyserverPublishResult,
    Mailbox,
    MailboxListResponse,
    MailboxStats,
    SendResult,
    SignatureStatus,
    TlsCertificateStatus,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "Alias",
    "AliasListResponse",
    "ApiKey",
    "AsyncMailcue",
    "AttachmentInfo",
    "AuthenticationError",
    "AuthorizationError",
    "BulkInjectResponse",
    "ConflictError",
    "CreatedApiKey",
    "DnsCheckResponse",
    "DnsRecordInfo",
    "Domain",
    "DomainDetail",
    "DomainListResponse",
    "EmailDetail",
    "EmailListResponse",
    "EmailSummary",
    "Event",
    "FolderInfo",
    "GpgEmailInfo",
    "GpgKey",
    "GpgKeyExport",
    "GpgKeyListResponse",
    "HealthResponse",
    "KeyserverPublishResult",
    "Mailbox",
    "MailboxListResponse",
    "MailboxStats",
    "Mailcue",
    "MailcueError",
    "NetworkError",
    "NotFoundError",
    "RateLimitError",
    "SendResult",
    "ServerError",
    "SignatureStatus",
    "TimeoutError",
    "TlsCertificateStatus",
    "ValidationError",
    "__version__",
]
