"""028 -- add persisted deliverability alerts.

Revision ID: 028_deliverability_alerts
Revises: 027_deliverability_artifacts
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "028_deliverability_alerts"
down_revision: str | None = "027_deliverability_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deliverability_alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("mailbox_id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("policy_id", sa.String(length=36), nullable=True),
        sa.Column("deduplication_key", sa.String(length=255), nullable=False),
        sa.Column("alert_type", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["mailbox_id"], ["mailboxes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["deliverability_policies.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["report_id"], ["deliverability_reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["deliverability_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deduplication_key", name="uq_deliverability_alert_deduplication_key"),
    )
    for column in ("user_id", "mailbox_id"):
        op.create_index(f"ix_deliverability_alerts_{column}", "deliverability_alerts", [column])
    op.create_index(
        "ix_deliverability_alerts_user_ack_created",
        "deliverability_alerts",
        ["user_id", "acknowledged", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("deliverability_alerts")
