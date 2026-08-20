"""029 -- add tenant-scoped email validation feedback.

Revision ID: 029_email_validation_feedback
Revises: 028_deliverability_alerts
Create Date: 2026-08-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "029_email_validation_feedback"
down_revision: str | None = "028_deliverability_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_validation_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("smtp_code", sa.Integer(), nullable=True),
        sa.Column("enhanced_status", sa.String(length=16), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_validation_feedback_user_email_time",
        "email_validation_feedback",
        ["user_id", "email_hash", "occurred_at"],
    )
    op.create_index(
        "ix_validation_feedback_user_domain_time",
        "email_validation_feedback",
        ["user_id", "domain", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("email_validation_feedback")
