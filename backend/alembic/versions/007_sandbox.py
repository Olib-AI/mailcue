"""007 -- create messaging sandbox tables.

Revision ID: 007_sandbox
Revises: 006_mta_sts_tls_rpt
Create Date: 2026-03-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "007_sandbox"
down_revision: str | None = "006_mta_sts_tls_rpt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sandbox_providers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("credentials", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "sandbox_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("sandbox_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("conversation_type", sa.String(50), nullable=False, server_default="direct"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "sandbox_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("sandbox_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("sandbox_conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("sender", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(50), nullable=False, server_default="text"),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("raw_request", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("raw_response", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "sandbox_webhook_endpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("sandbox_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("secret", sa.String(255), nullable=True),
        sa.Column("event_types", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "sandbox_webhook_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "endpoint_id",
            sa.String(36),
            sa.ForeignKey("sandbox_webhook_endpoints.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.String(36),
            sa.ForeignKey("sandbox_messages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sandbox_webhook_deliveries")
    op.drop_table("sandbox_webhook_endpoints")
    op.drop_table("sandbox_messages")
    op.drop_table("sandbox_conversations")
    op.drop_table("sandbox_providers")
