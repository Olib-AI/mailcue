"""025 -- persist immutable deliverability reports.

Revision ID: 025_deliverability_reports
Revises: 024_mailbox_purpose
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "025_deliverability_reports"
down_revision: str | None = "024_mailbox_purpose"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deliverability_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("mailbox_id", sa.String(length=36), nullable=False),
        sa.Column("mailbox_address", sa.String(length=255), nullable=False),
        sa.Column("folder", sa.String(length=255), nullable=False),
        sa.Column("uid", sa.String(length=255), nullable=False),
        sa.Column("message_id", sa.String(length=998), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("score_version", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("is_baseline", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mailbox_id"], ["mailboxes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mailbox_id",
            "folder",
            "uid",
            "raw_sha256",
            "score_version",
            name="uq_deliverability_report_message_version",
        ),
    )
    op.create_index(
        "ix_deliverability_reports_mailbox_id", "deliverability_reports", ["mailbox_id"]
    )
    op.create_index("ix_deliverability_reports_user_id", "deliverability_reports", ["user_id"])
    op.create_index(
        "ix_deliverability_reports_mailbox_created",
        "deliverability_reports",
        ["mailbox_id", "created_at", "id"],
    )
    op.create_index(
        "ix_deliverability_reports_user_created",
        "deliverability_reports",
        ["user_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_table("deliverability_reports")
