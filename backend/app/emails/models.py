"""Persistence for email-validation risk calibration and staged sending."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


class EmailValidationFeedback(Base):
    """One delivery outcome used to calibrate catch-all risk.

    Rows are tenant-owned, but the domain and provider columns are also read in
    aggregate across tenants. Catch-all behaviour belongs to the receiving
    domain rather than to whoever happened to query it, and scoping every
    lookup to one tenant guarantees a permanent cold start.
    """

    __tablename__ = "email_validation_feedback"
    __table_args__ = (
        Index("ix_validation_feedback_user_email_time", "user_id", "email_hash", "occurred_at"),
        Index("ix_validation_feedback_user_domain_time", "user_id", "domain", "occurred_at"),
        Index("ix_validation_feedback_domain_time", "domain", "occurred_at"),
        Index("ix_validation_feedback_provider_time", "provider_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    smtp_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enhanced_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    # api, dsn, or webhook. Distinguishes self-reported outcomes from bounces
    # the server observed directly.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="api")
    # Score this address was given before the outcome was known, when a
    # prediction was recorded. Drives calibration reporting.
    predicted_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EmailValidationPrediction(Base):
    """A risk score issued for one address, retained to measure calibration.

    A score presented as a probability is only a probability if it has been
    checked against outcomes. Storing the prediction lets a later bounce or
    delivery be joined back to what the model claimed at the time.
    """

    __tablename__ = "email_validation_prediction"
    __table_args__ = (
        Index("ix_validation_prediction_email_time", "email_hash", "created_at"),
        Index("ix_validation_prediction_user_time", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EmailSendCanary(Base):
    """A staged send that measures a domain's real bounce rate before committing.

    SMTP has no recall, so the only way to bound exposure on an accept-all
    domain is to not commit the whole batch at once. A small sample goes out
    first, the notification window is observed, and the remainder is released
    only if nothing bounced.
    """

    __tablename__ = "email_send_canary"
    __table_args__ = (
        Index("ix_send_canary_user_created", "user_id", "created_at"),
        Index("ix_send_canary_status_due", "status", "decision_due_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    hold_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    # Fraction of the sample allowed to hard bounce before the remainder is
    # withheld. Zero means any hard bounce blocks the batch.
    bounce_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    from_address: Mapped[str] = mapped_column(String(320), nullable=False)
    from_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_type: Mapped[str] = mapped_column(String(8), nullable=False, default="plain")
    reply_to: Mapped[str | None] = mapped_column(String(320), nullable=True)
    auto_release: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    sample_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class EmailSendCanaryRecipient(Base):
    """One recipient inside a staged send."""

    __tablename__ = "email_send_canary_recipient"
    __table_args__ = (
        Index("ix_send_canary_recipient_canary", "canary_id", "role"),
        Index("ix_send_canary_recipient_hash", "email_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    canary_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("email_send_canary.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    # sample for the addresses sent first, held for the remainder.
    role: Mapped[str] = mapped_column(String(8), nullable=False, default="held")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    smtp_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enhanced_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DomainSendSuppression(Base):
    """A recipient domain paused after its measured bounce rate crossed a limit.

    The first tenant to discover that a domain bounces protects every later
    send to it, which is the property that makes accept-all traffic safe to
    attempt at all.
    """

    __tablename__ = "domain_send_suppression"
    __table_args__ = (Index("ix_domain_suppression_domain", "domain", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    hard_bounces: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MailboxBounceScan(Base):
    """Progress marker for the automatic bounce scan of one mailbox."""

    __tablename__ = "mailbox_bounce_scan"
    __table_args__ = (Index("ix_mailbox_bounce_scan_mailbox", "mailbox", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    mailbox: Mapped[str] = mapped_column(String(320), nullable=False)
    last_uid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
