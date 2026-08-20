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
    scopes: List[str] = Field(default_factory=lambda: ["*"])
    allowed_mailboxes: Optional[List[str]] = None


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


class EmailValidationSyntax(_Base):
    """Syntax check results."""

    is_valid: bool
    local_part: Optional[str] = None
    domain: Optional[str] = None
    error: Optional[str] = None


class EmailValidationDns(_Base):
    """DNS MX/NS/A check results."""

    is_valid: bool
    has_mx: bool
    has_ns: bool
    has_a: bool
    has_aaaa: bool = False
    null_mx: bool = False
    mx_records: List[str] = Field(default_factory=list)
    ns_records: List[str] = Field(default_factory=list)
    a_records: List[str] = Field(default_factory=list)
    aaaa_records: List[str] = Field(default_factory=list)
    status: Literal["valid", "invalid", "undetermined"] = "invalid"
    error_code: Optional[str] = None
    error: Optional[str] = None


class EmailValidationControlProbe(_Base):
    """One synthetic recipient probed alongside the address under test."""

    shape: str
    smtp_code: Optional[int] = None
    smtp_response: Optional[str] = None
    verdict: Literal["mailbox_absent", "mailbox_present", "temporary", "policy", "unknown"]
    latency_ms: Optional[float] = None


class EmailValidationMailbox(_Base):
    """SMTP RCPT TO probe check results."""

    is_valid: Optional[bool] = None
    smtp_code: Optional[int] = None
    smtp_response: Optional[str] = None
    catch_all: Optional[bool] = None
    transport: Literal["direct", "mailcue_tunnel", "none"] = "none"
    reason_code: Optional[str] = None
    error: Optional[str] = None
    enhanced_status: Optional[str] = None
    mx_host: Optional[str] = None
    target_latency_ms: Optional[float] = None
    control_median_latency_ms: Optional[float] = None
    control_probes: List[EmailValidationControlProbe] = Field(default_factory=list)
    controls_accepted: int = 0
    controls_rejected: int = 0
    controls_inconclusive: int = 0
    selective_recipient_validation: Optional[bool] = None
    order_degraded: bool = False
    sender_reputation_signal: bool = False


class EmailValidationProvider(_Base):
    """Receiving provider inferred from the domain's MX records."""

    id: str
    name: str
    category: Literal[
        "hosted_mailbox",
        "security_gateway",
        "consumer",
        "self_hosted",
        "forwarder",
        "parked",
        "unroutable",
        "unknown",
    ]
    matched_host: Optional[str] = None
    fronts_backend: bool = False
    accept_all_bounce_prior: float = 0.125
    inferred_backend: Optional[str] = None
    notes: str = ""


class EmailValidationLocalPart(_Base):
    """Offline risk signals derived from the local part."""

    shape: str
    is_role_account: bool = False
    is_placeholder: bool = False
    is_trap_marker: bool = False
    has_plus_tag: bool = False
    gibberish_score: float = 0.0
    digit_ratio: float = 0.0
    risk_delta: float = 0.0
    notes: List[str] = Field(default_factory=list)


class EmailValidationDomainSignals(_Base):
    """Passive domain evidence collected without contacting the MX."""

    age_days: Optional[int] = None
    expires_in_days: Optional[int] = None
    has_spf: bool = False
    has_dmarc: bool = False
    dmarc_policy: Optional[str] = None
    has_mta_sts: bool = False
    has_tls_rpt: bool = False
    wildcard_dns: bool = False
    parked: bool = False
    inferred_backend: Optional[str] = None
    risk_delta: float = 0.0
    notes: List[str] = Field(default_factory=list)


class EmailValidationDisposable(_Base):
    """Disposable domain check results."""

    is_disposable: bool
    is_forwarding_alias: bool = False
    error: Optional[str] = None


class EmailValidationRiskContribution(_Base):
    """One named adjustment applied to the base rate, expressed in log-odds."""

    label: str
    delta: float
    detail: str = ""


class EmailValidationCatchAllRisk(_Base):
    """Hard-bounce estimate for an accept-all recipient.

    ``score`` is a probability. ``base_rate`` is the pooled rate for the
    destination before any per-address adjustment, so the two together show how
    much of the estimate came from evidence about this address specifically.
    """

    score: float
    level: Literal["low", "medium", "high", "unknown"]
    recommended_action: Literal["send", "caution", "hold"]
    source: Literal[
        "no_history",
        "exact_history",
        "domain_history",
        "shared_domain_history",
        "provider_history",
        "provider_prior",
    ]
    sample_size: int
    explanation: str
    base_rate: float = 0.125
    provider_id: Optional[str] = None
    provider_rate: Optional[float] = None
    confidence: float = 0.3
    contributions: List[EmailValidationRiskContribution] = Field(default_factory=list)


class EmailValidationFeedbackResponse(_Base):
    """Acknowledgement returned after recording a delivery outcome."""

    recorded: bool
    outcome: Literal["delivered", "hard_bounce", "soft_bounce"]


class EmailValidationResponse(_Base):
    """Complete email validation details."""

    email: str
    is_valid: bool
    status: Literal["valid", "invalid", "undetermined", "disposable", "catch_all"]
    verdict: Literal["deliverable", "undeliverable", "risky", "unknown"] = "unknown"
    deliverable: Optional[bool] = None
    confidence: float = 0.0
    reason: str = ""
    syntax: EmailValidationSyntax
    dns: EmailValidationDns
    mailbox: EmailValidationMailbox
    disposable: EmailValidationDisposable
    catch_all_risk: Optional[EmailValidationCatchAllRisk] = None
    provider: Optional[EmailValidationProvider] = None
    local_part: Optional[EmailValidationLocalPart] = None
    domain_signals: Optional[EmailValidationDomainSignals] = None


class EmailValidationBatchItem(_Base):
    """One address inside a batch validation."""

    email: str
    status: Literal["valid", "invalid", "undetermined", "disposable", "catch_all"]
    verdict: Literal["deliverable", "undeliverable", "risky", "unknown"]
    deliverable: Optional[bool] = None
    reason: str = ""
    provider_id: Optional[str] = None
    risk_score: float = 0.0
    recommended_action: Literal["send", "caution", "hold"] = "caution"
    matches_domain_pattern: Optional[bool] = None
    permutation_variant: bool = False
    catch_all_risk: Optional[EmailValidationCatchAllRisk] = None
    error: Optional[str] = None


class EmailValidationBudgetSelection(_Base):
    """Addresses that fit inside a target blended bounce rate."""

    target_bounce_rate: float
    projected_bounce_rate: float
    included: List[str] = Field(default_factory=list)
    excluded: List[str] = Field(default_factory=list)
    included_count: int = 0
    excluded_count: int = 0


class EmailValidationBatchSummary(_Base):
    """Aggregate counts for a batch validation."""

    total: int
    valid: int
    invalid: int
    catch_all: int
    undetermined: int
    disposable: int
    mean_risk_score: float = 0.0
    projected_bounce_rate: float = 0.0


class EmailValidationBatchResponse(_Base):
    """Result of validating a batch of addresses."""

    results: List[EmailValidationBatchItem] = Field(default_factory=list)
    summary: EmailValidationBatchSummary
    selection: Optional[EmailValidationBudgetSelection] = None


class EmailValidationCalibrationBin(_Base):
    """One reliability-diagram bucket."""

    lower: float
    upper: float
    count: int
    predicted_mean: float
    observed_rate: float


class EmailValidationCalibrationResponse(_Base):
    """Measured agreement between issued scores and the outcomes that followed."""

    sample_size: int
    brier_score: Optional[float] = None
    mean_predicted: Optional[float] = None
    observed_rate: Optional[float] = None
    bins: List[EmailValidationCalibrationBin] = Field(default_factory=list)


class EmailBounceIngestRecipient(_Base):
    """One recipient outcome extracted from a delivery status notification."""

    recipient: str
    outcome: Literal["delivered", "hard_bounce", "soft_bounce"]
    status: Optional[str] = None
    smtp_code: Optional[int] = None
    diagnostic_code: Optional[str] = None


class EmailBounceIngestResponse(_Base):
    """Outcome of parsing and recording one notification."""

    is_dsn: bool
    recorded: int = 0
    recipients: List[EmailBounceIngestRecipient] = Field(default_factory=list)


class SendCanaryRecipient(_Base):
    """One recipient inside a staged send."""

    email: str
    role: Literal["sample", "held"]
    status: Literal[
        "pending",
        "sent",
        "delivered",
        "hard_bounce",
        "soft_bounce",
        "released",
        "blocked",
        "skipped",
    ]
    risk_score: Optional[float] = None
    smtp_code: Optional[int] = None
    enhanced_status: Optional[str] = None
    sent_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class SendCanaryResponse(_Base):
    """State of one staged send."""

    id: str
    name: str = ""
    status: Literal["pending", "probing", "released", "blocked", "cancelled", "failed"]
    sample_size: int
    hold_minutes: int
    bounce_threshold: float = 0.0
    auto_release: bool = True
    from_address: str
    subject: str = ""
    created_at: datetime
    sample_sent_at: Optional[datetime] = None
    decision_due_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    decision_reason: Optional[str] = None
    total_recipients: int = 0
    sample_recipients: int = 0
    held_recipients: int = 0
    hard_bounces: int = 0
    soft_bounces: int = 0
    recipients: List[SendCanaryRecipient] = Field(default_factory=list)


class SendCanaryListResponse(_Base):
    """Staged sends for the calling tenant."""

    canaries: List[SendCanaryResponse] = Field(default_factory=list)
    total: int = 0


class DomainSuppressionEntry(_Base):
    """A recipient domain paused after its measured bounce rate crossed the limit."""

    domain: str
    reason: str = ""
    hard_bounces: int = 0
    observations: int = 0
    created_at: datetime
    expires_at: Optional[datetime] = None


class DomainSuppressionListResponse(_Base):
    """Currently suppressed recipient domains."""

    suppressions: List[DomainSuppressionEntry] = Field(default_factory=list)
    total: int = 0
