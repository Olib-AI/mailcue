"""009 -- create forwarding_rules table.

Revision ID: 009_forwarding_rules
Revises: 008_httpbin
Create Date: 2026-03-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "009_forwarding_rules"
down_revision: str | None = "008_httpbin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forwarding_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("match_from", sa.String(500), nullable=True),
        sa.Column("match_to", sa.String(500), nullable=True),
        sa.Column("match_subject", sa.String(500), nullable=True),
        sa.Column("match_mailbox", sa.String(255), nullable=True),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("action_config", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("forwarding_rules")
