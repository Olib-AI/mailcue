"""016 -- API key permissions: per-key scopes and mailbox allow-list.

Adds ``scopes`` and ``allowed_mailboxes`` JSON columns to ``api_keys``.
Existing keys are backfilled with ``["*"]`` (full access) and a null
mailbox allow-list so their behaviour is unchanged.

Revision ID: 016_api_key_permissions
Revises: 015_domain_record_audit
Create Date: 2026-06-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "016_api_key_permissions"
down_revision: str | None = "015_domain_record_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column in [c["name"] for c in inspector.get_columns(table)]


def upgrade() -> None:
    if not _column_exists("api_keys", "scopes"):
        # server_default backfills existing rows with full access.
        op.add_column(
            "api_keys",
            sa.Column("scopes", sa.JSON(), nullable=False, server_default='["*"]'),
        )
    if not _column_exists("api_keys", "allowed_mailboxes"):
        op.add_column(
            "api_keys",
            sa.Column("allowed_mailboxes", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_column("allowed_mailboxes")
        batch_op.drop_column("scopes")
