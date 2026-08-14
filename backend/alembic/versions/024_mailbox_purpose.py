"""024 -- add mailbox purpose.

Revision ID: 024_mailbox_purpose
Revises: 023_reset_mta_sts_verification
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "024_mailbox_purpose"
down_revision: str | None = "023_reset_mta_sts_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("mailboxes")}
    if "purpose" not in columns:
        op.add_column(
            "mailboxes",
            sa.Column("purpose", sa.String(length=32), nullable=False, server_default="standard"),
        )


def downgrade() -> None:
    op.drop_column("mailboxes", "purpose")
