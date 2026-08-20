"""030 -- provider-aware catch-all risk, calibration, and staged sending.

Revision ID: 030_catchall_risk_and_canary
Revises: 029_email_validation_feedback
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "030_catchall_risk_and_canary"
down_revision: str | None = "029_email_validation_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "email_validation_feedback",
        sa.Column("provider_id", sa.String(length=48), nullable=True),
    )
    op.add_column(
        "email_validation_feedback",
        sa.Column("source", sa.String(length=16), nullable=False, server_default="api"),
    )
    op.add_column(
        "email_validation_feedback",
        sa.Column("predicted_score", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_validation_feedback_domain_time",
        "email_validation_feedback",
        ["domain", "occurred_at"],
    )
    op.create_index(
        "ix_validation_feedback_provider_time",
        "email_validation_feedback",
        ["provider_id", "occurred_at"],
    )

    op.create_table(
        "email_validation_prediction",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("provider_id", sa.String(length=48), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_validation_prediction_email_time",
        "email_validation_prediction",
        ["email_hash", "created_at"],
    )
    op.create_index(
        "ix_validation_prediction_user_time",
        "email_validation_prediction",
        ["user_id", "created_at"],
    )

    op.create_table(
        "email_send_canary",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("hold_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("bounce_threshold", sa.Float(), nullable=False, server_default="0"),
        sa.Column("from_address", sa.String(length=320), nullable=False),
        sa.Column("from_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("subject", sa.String(length=998), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_type", sa.String(length=8), nullable=False, server_default="plain"),
        sa.Column("reply_to", sa.String(length=320), nullable=True),
        sa.Column("auto_release", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_send_canary_user_created", "email_send_canary", ["user_id", "created_at"])
    op.create_index(
        "ix_send_canary_status_due", "email_send_canary", ["status", "decision_due_at"]
    )

    op.create_table(
        "email_send_canary_recipient",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("canary_id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False, server_default="held"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("smtp_code", sa.Integer(), nullable=True),
        sa.Column("enhanced_status", sa.String(length=16), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["canary_id"], ["email_send_canary.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_send_canary_recipient_canary", "email_send_canary_recipient", ["canary_id", "role"]
    )
    op.create_index("ix_send_canary_recipient_hash", "email_send_canary_recipient", ["email_hash"])

    op.create_table(
        "domain_send_suppression",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("hard_bounces", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_domain_suppression_domain", "domain_send_suppression", ["domain"], unique=True
    )

    op.create_table(
        "mailbox_bounce_scan",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mailbox", sa.String(length=320), nullable=False),
        sa.Column("last_uid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mailbox_bounce_scan_mailbox", "mailbox_bounce_scan", ["mailbox"], unique=True
    )


def downgrade() -> None:
    op.drop_table("mailbox_bounce_scan")
    op.drop_table("domain_send_suppression")
    op.drop_table("email_send_canary_recipient")
    op.drop_table("email_send_canary")
    op.drop_table("email_validation_prediction")
    op.drop_index("ix_validation_feedback_provider_time", table_name="email_validation_feedback")
    op.drop_index("ix_validation_feedback_domain_time", table_name="email_validation_feedback")
    op.drop_column("email_validation_feedback", "predicted_score")
    op.drop_column("email_validation_feedback", "source")
    op.drop_column("email_validation_feedback", "provider_id")
