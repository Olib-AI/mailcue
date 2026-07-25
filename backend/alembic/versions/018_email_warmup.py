"""018 -- controlled email warmup accounts, campaigns, and event history.

Revision ID: 018_email_warmup
Revises: 017_catch_all_settings
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "018_email_warmup"
down_revision: str | None = "017_catch_all_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "warmup_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("smtp_host", sa.String(255), nullable=False),
        sa.Column("smtp_port", sa.Integer(), nullable=False),
        sa.Column("smtp_security", sa.String(12), nullable=False),
        sa.Column("imap_host", sa.String(255), nullable=False),
        sa.Column("imap_port", sa.Integer(), nullable=False),
        sa.Column("imap_security", sa.String(12), nullable=False),
        sa.Column("username", sa.String(320), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "warmup_campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("local_address", sa.String(320), nullable=False),
        sa.Column("account_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("start_daily_volume", sa.Integer(), nullable=False),
        sa.Column("daily_ramp", sa.Integer(), nullable=False),
        sa.Column("max_daily_volume", sa.Integer(), nullable=False),
        sa.Column("min_delay_minutes", sa.Integer(), nullable=False),
        sa.Column("max_delay_minutes", sa.Integer(), nullable=False),
        sa.Column("reply_rate", sa.Integer(), nullable=False),
        sa.Column("active_hour_start", sa.Integer(), nullable=False),
        sa.Column("active_hour_end", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("messages_sent_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("volume_date", sa.String(10), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "warmup_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=True),
        sa.Column("direction", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("message_id", sa.String(255), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_warmup_events_campaign_id", "warmup_events", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_warmup_events_campaign_id", table_name="warmup_events")
    op.drop_table("warmup_events")
    op.drop_table("warmup_campaigns")
    op.drop_table("warmup_accounts")
