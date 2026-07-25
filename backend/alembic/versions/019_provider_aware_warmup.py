"""019 -- provider-aware warmup pacing and SMTP feedback.

Revision ID: 019_provider_aware_warmup
Revises: 018_email_warmup
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "019_provider_aware_warmup"
down_revision: str | None = "018_email_warmup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("warmup_events") as batch_op:
        batch_op.add_column(sa.Column("provider", sa.String(40), nullable=True))
        batch_op.add_column(sa.Column("smtp_code", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("enhanced_status", sa.String(16), nullable=True))

    op.create_table(
        "warmup_provider_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="healthy"),
        sa.Column("sent_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("volume_date", sa.String(10), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("paused_until", sa.DateTime(), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(), nullable=True),
        sa.Column("last_smtp_code", sa.Integer(), nullable=True),
        sa.Column("last_enhanced_status", sa.String(16), nullable=True),
        sa.Column("last_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("campaign_id", "provider"),
    )
    op.create_index(
        "ix_warmup_provider_states_campaign_id",
        "warmup_provider_states",
        ["campaign_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_warmup_provider_states_campaign_id", table_name="warmup_provider_states")
    op.drop_table("warmup_provider_states")
    with op.batch_alter_table("warmup_events") as batch_op:
        batch_op.drop_column("enhanced_status")
        batch_op.drop_column("smtp_code")
        batch_op.drop_column("provider")
