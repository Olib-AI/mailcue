"""011 -- create aliases table.

Revision ID: 011_aliases
Revises: 010_mailbox_signature
Create Date: 2026-03-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "011_aliases"
down_revision: str | None = "010_mailbox_signature"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "aliases" not in inspector.get_table_names():
        op.create_table(
            "aliases",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_address", sa.String(255), unique=True, index=True, nullable=False),
            sa.Column("destination_address", sa.String(255), nullable=False),
            sa.Column("domain", sa.String(255), index=True, nullable=False),
            sa.Column("is_catchall", sa.Boolean(), server_default="0", nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("aliases")
