"""010 -- add signature column to mailboxes.

Revision ID: 010_mailbox_signature
Revises: 009_forwarding_rules
Create Date: 2026-03-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "010_mailbox_signature"
down_revision: str | None = "009_forwarding_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("mailboxes")]
    if "signature" not in columns:
        op.add_column(
            "mailboxes",
            sa.Column("signature", sa.Text(), server_default="", nullable=False),
        )


def downgrade() -> None:
    op.drop_column("mailboxes", "signature")
