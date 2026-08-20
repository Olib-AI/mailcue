"""Pydantic request / response schemas for the email module."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

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

    score_version: str = "2.3"
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


class EmailValidationControlProbe(BaseModel):
    """One synthetic recipient probed alongside the address under test."""

    shape: str
    smtp_code: int | None = None
    smtp_response: str | None = None
    verdict: Literal["mailbox_absent", "mailbox_present", "temporary", "policy", "unknown"]
    latency_ms: float | None = None


class EmailValidationMailbox(BaseModel):
    """Result of SMTP probe check."""

    is_valid: bool | None = None
    smtp_code: int | None = None
    smtp_response: str | None = None
    catch_all: bool | None = None
    transport: Literal["direct", "mailcue_tunnel", "none"] = "none"
    reason_code: str | None = None
    error: str | None = None
    enhanced_status: str | None = None
    mx_host: str | None = None
    target_latency_ms: float | None = None
    control_median_latency_ms: float | None = None
    control_probes: list[EmailValidationControlProbe] = []
    controls_accepted: int = 0
    controls_rejected: int = 0
    controls_inconclusive: int = 0
    # True when the destination refused at least one synthetic recipient, which
    # proves it evaluates recipients rather than accepting everything.
    selective_recipient_validation: bool | None = None
    # True when the first control was accepted but a later one was refused, so
    # the refusals reflect connection throttling rather than recipient logic.
    order_degraded: bool = False
    # True when the destination reacted to the probing host's reputation. Its
    # answers then describe the sender, not the mailbox.
    sender_reputation_signal: bool = False


class EmailValidationProvider(BaseModel):
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
    matched_host: str | None = None
    fronts_backend: bool = False
    accept_all_bounce_prior: float
    inferred_backend: str | None = None
    notes: str = ""


class EmailValidationLocalPart(BaseModel):
    """Offline risk signals derived from the local part."""

    shape: str
    is_role_account: bool = False
    is_placeholder: bool = False
    is_trap_marker: bool = False
    has_plus_tag: bool = False
    gibberish_score: float = 0.0
    digit_ratio: float = 0.0
    risk_delta: float = 0.0
    notes: list[str] = []


class EmailValidationDomainSignals(BaseModel):
    """Passive domain-level evidence collected without contacting the MX."""

    age_days: int | None = None
    expires_in_days: int | None = None
    has_spf: bool = False
    has_dmarc: bool = False
    dmarc_policy: str | None = None
    has_mta_sts: bool = False
    has_tls_rpt: bool = False
    wildcard_dns: bool = False
    parked: bool = False
    inferred_backend: str | None = None
    risk_delta: float = 0.0
    notes: list[str] = []


class EmailValidationDisposable(BaseModel):
    """Result of temporary/disposable domain check."""

    is_disposable: bool
    is_forwarding_alias: bool = False
    error: str | None = None


class EmailValidationRiskContribution(BaseModel):
    """One named adjustment applied to the base rate, expressed in log-odds."""

    label: str
    delta: float
    detail: str = ""


class EmailValidationCatchAllRisk(BaseModel):
    """Hard-bounce estimate for an SMTP accept-all recipient.

    ``score`` is a probability, and ``base_rate`` shows the pooled rate before
    any per-address adjustment so callers can see how much of the estimate came
    from evidence about this address rather than about its destination.
    """

    score: float = Field(ge=0, le=1)
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
    sample_size: int = Field(ge=0)
    explanation: str
    base_rate: float = Field(default=0.125, ge=0, le=1)
    provider_id: str | None = None
    provider_rate: float | None = None
    confidence: float = Field(default=0.3, ge=0, le=1)
    contributions: list[EmailValidationRiskContribution] = []


class EmailValidationFeedbackRequest(BaseModel):
    """Record an organic delivery outcome for future catch-all scoring."""

    email: str
    outcome: Literal["delivered", "hard_bounce", "soft_bounce"]
    smtp_code: int | None = Field(default=None, ge=100, le=599)
    enhanced_status: str | None = Field(default=None, max_length=16)

    @model_validator(mode="after")
    def validate_status_classes(self) -> EmailValidationFeedbackRequest:
        expected_class = {"delivered": 2, "soft_bounce": 4, "hard_bounce": 5}[self.outcome]
        if self.smtp_code is not None and self.smtp_code // 100 != expected_class:
            raise ValueError(f"smtp_code must be {expected_class}xx for outcome {self.outcome}")
        if self.enhanced_status:
            if not re.fullmatch(r"[245]\.\d{1,3}\.\d{1,3}", self.enhanced_status):
                raise ValueError("enhanced_status must use RFC 3463 class.subject.detail format")
            first = self.enhanced_status.split(".", 1)[0]
            if int(first) != expected_class:
                raise ValueError(
                    f"enhanced_status must start with {expected_class}. for outcome {self.outcome}"
                )
        return self


class EmailValidationFeedbackResponse(BaseModel):
    """Acknowledgement for a stored validation feedback event."""

    recorded: bool
    outcome: Literal["delivered", "hard_bounce", "soft_bounce"]


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
    catch_all_risk: EmailValidationCatchAllRisk | None = None
    provider: EmailValidationProvider | None = None
    local_part: EmailValidationLocalPart | None = None
    domain_signals: EmailValidationDomainSignals | None = None


class EmailValidationBatchRequest(BaseModel):
    """Validate many addresses together so batch-level evidence can be used."""

    emails: list[str] = Field(min_length=1)
    # When set, the response also reports the largest subset whose blended
    # expected bounce rate stays under this ceiling. Reputation is judged on
    # the aggregate of a send, not on any single address.
    target_bounce_rate: float | None = Field(default=None, ge=0, le=1)
    include_domain_signals: bool = True


class EmailValidationBatchItem(BaseModel):
    """One address inside a batch validation."""

    email: str
    status: Literal["valid", "invalid", "undetermined", "disposable", "catch_all"]
    verdict: Literal["deliverable", "undeliverable", "risky", "unknown"]
    deliverable: bool | None = None
    reason: str
    provider_id: str | None = None
    risk_score: float = Field(ge=0, le=1)
    recommended_action: Literal["send", "caution", "hold"]
    # True when the local part matches the naming convention the rest of the
    # batch uses at this domain.
    matches_domain_pattern: bool | None = None
    # True when the batch contains several generated variants of one name at
    # this domain, of which at most one can be a live mailbox.
    permutation_variant: bool = False
    catch_all_risk: EmailValidationCatchAllRisk | None = None
    # RCPT latency for this recipient against the destination's baseline for
    # recipients it does not have. The gap between them is the strongest
    # available evidence that a mailbox lookup actually happened, so it is
    # reported for callers who want to audit or recalibrate a score.
    target_latency_ms: float | None = None
    control_median_latency_ms: float | None = None
    error: str | None = None


class EmailValidationBudgetSelection(BaseModel):
    """Addresses that fit inside a target blended bounce rate."""

    target_bounce_rate: float
    projected_bounce_rate: float
    included: list[str]
    excluded: list[str]
    included_count: int
    excluded_count: int


class EmailValidationBatchSummary(BaseModel):
    """Aggregate counts for a batch validation."""

    total: int
    valid: int
    invalid: int
    catch_all: int
    undetermined: int
    disposable: int
    mean_risk_score: float
    projected_bounce_rate: float


class EmailValidationBatchResponse(BaseModel):
    """Result of validating a batch of addresses."""

    results: list[EmailValidationBatchItem]
    summary: EmailValidationBatchSummary
    selection: EmailValidationBudgetSelection | None = None


class EmailValidationCalibrationBin(BaseModel):
    """One reliability-diagram bucket."""

    lower: float
    upper: float
    count: int
    predicted_mean: float
    observed_rate: float


class EmailValidationCalibrationResponse(BaseModel):
    """Measured agreement between issued scores and the outcomes that followed."""

    sample_size: int
    brier_score: float | None = None
    mean_predicted: float | None = None
    observed_rate: float | None = None
    bins: list[EmailValidationCalibrationBin] = []


class EmailBounceIngestRequest(BaseModel):
    """Submit a raw delivery status notification for outcome extraction."""

    raw_message: str = Field(min_length=1, max_length=2_000_000)


class EmailBounceIngestRecipient(BaseModel):
    """One recipient outcome extracted from a notification."""

    recipient: str
    outcome: Literal["delivered", "hard_bounce", "soft_bounce"]
    status: str | None = None
    smtp_code: int | None = None
    diagnostic_code: str | None = None


class EmailBounceIngestResponse(BaseModel):
    """Outcome of parsing and recording one notification."""

    is_dsn: bool
    recorded: int
    recipients: list[EmailBounceIngestRecipient] = []


class CreateSendCanaryRequest(BaseModel):
    """Stage a send so a small sample proves the domain before the rest goes out."""

    recipients: list[str] = Field(min_length=1)
    from_address: str
    subject: str
    body: str = ""
    name: str = ""
    from_name: str = ""
    body_type: Literal["plain", "html"] = "plain"
    reply_to: str | None = None
    sample_size: int | None = Field(default=None, ge=1, le=50)
    hold_minutes: int | None = Field(default=None, ge=1, le=10_080)
    bounce_threshold: float = Field(default=0.0, ge=0, le=1)
    auto_release: bool = True


class SendCanaryRecipient(BaseModel):
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
    risk_score: float | None = None
    smtp_code: int | None = None
    enhanced_status: str | None = None
    sent_at: datetime | None = None
    resolved_at: datetime | None = None


class SendCanaryResponse(BaseModel):
    """State of one staged send."""

    id: str
    name: str
    status: Literal["pending", "probing", "released", "blocked", "cancelled", "failed"]
    sample_size: int
    hold_minutes: int
    bounce_threshold: float
    auto_release: bool
    from_address: str
    subject: str
    created_at: datetime
    sample_sent_at: datetime | None = None
    decision_due_at: datetime | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    total_recipients: int
    sample_recipients: int
    held_recipients: int
    hard_bounces: int
    soft_bounces: int
    recipients: list[SendCanaryRecipient] = []


class SendCanaryListResponse(BaseModel):
    """Paginated staged sends for the calling tenant."""

    canaries: list[SendCanaryResponse]
    total: int


class DomainSuppressionEntry(BaseModel):
    """A recipient domain paused after its measured bounce rate crossed the limit."""

    domain: str
    reason: str
    hard_bounces: int
    observations: int
    created_at: datetime
    expires_at: datetime | None = None


class DomainSuppressionListResponse(BaseModel):
    """Currently suppressed recipient domains."""

    suppressions: list[DomainSuppressionEntry]
    total: int
