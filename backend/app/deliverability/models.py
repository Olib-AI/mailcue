"""Persistence models for immutable deliverability reports."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DeliverabilityReportRecord(Base):
    """Immutable snapshot of one scoring model run over one raw message."""

    __tablename__ = "deliverability_reports"
    __table_args__ = (
        UniqueConstraint(
            "mailbox_id",
            "folder",
            "uid",
            "raw_sha256",
            "score_version",
            name="uq_deliverability_report_message_version",
        ),
        Index(
            "ix_deliverability_reports_mailbox_created",
            "mailbox_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_deliverability_reports_user_created",
            "user_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mailbox_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mailbox_address: Mapped[str] = mapped_column(String(255), nullable=False)
    folder: Mapped[str] = mapped_column(String(255), nullable=False)
    uid: Mapped[str] = mapped_column(String(255), nullable=False)
    message_id: Mapped[str] = mapped_column(String(998), nullable=False, default="")
    raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    score_version: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class DeliverabilityRun(Base):
    """Auditable lifecycle for optional and asynchronous report enrichments."""

    __tablename__ = "deliverability_runs"
    __table_args__ = (
        Index("ix_deliverability_runs_mailbox_created", "mailbox_id", "created_at", "id"),
        Index("ix_deliverability_runs_status_created", "status", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mailbox_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("deliverability_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    requested_checks: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    capability_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeliverabilityPolicy(Base):
    """Tenant-owned CI gate and regression policy."""

    __tablename__ = "deliverability_policies"
    __table_args__ = (
        UniqueConstraint("mailbox_id", "name", name="uq_deliverability_policy_mailbox_name"),
        Index("ix_deliverability_policies_user_enabled", "user_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mailbox_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    minimum_score: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    maximum_regression: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    fail_on_statuses: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: ["fail"]
    )
    required_check_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    required_capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class DeliverabilityPolicyEvaluation(Base):
    """Immutable CI policy result for one report."""

    __tablename__ = "deliverability_policy_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "report_id", name="uq_deliverability_policy_evaluation_report"
        ),
        Index("ix_deliverability_policy_evaluations_created", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    policy_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("deliverability_policies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("deliverability_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class DeliverabilityProvider(Base):
    """Encrypted configuration for an optional preview or placement adapter."""

    __tablename__ = "deliverability_providers"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_deliverability_provider_user_name"),
        Index("ix_deliverability_providers_user_kind", "user_id", "kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_checked")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class DeliverabilitySchedule(Base):
    """Recurring latest-message analysis without storing raw message content."""

    __tablename__ = "deliverability_schedules"
    __table_args__ = (
        UniqueConstraint("mailbox_id", "name", name="uq_deliverability_schedule_mailbox_name"),
        Index("ix_deliverability_schedules_due", "enabled", "next_run_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mailbox_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    policy_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("deliverability_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    requested_checks: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class DeliverabilityArtifact(Base):
    """Tenant-protected binary output such as a local render screenshot."""

    __tablename__ = "deliverability_artifacts"
    __table_args__ = (
        Index("ix_deliverability_artifacts_run_created", "run_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("deliverability_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(127), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class DeliverabilityAlert(Base):
    """Persistent user-visible alert generated by policies, schedules, or providers."""

    __tablename__ = "deliverability_alerts"
    __table_args__ = (
        UniqueConstraint("deduplication_key", name="uq_deliverability_alert_deduplication_key"),
        Index(
            "ix_deliverability_alerts_user_ack_created", "user_id", "acknowledged", "created_at"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mailbox_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("deliverability_reports.id", ondelete="CASCADE"), nullable=True
    )
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("deliverability_runs.id", ondelete="CASCADE"), nullable=True
    )
    policy_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("deliverability_policies.id", ondelete="SET NULL"), nullable=True
    )
    deduplication_key: Mapped[str] = mapped_column(String(255), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
