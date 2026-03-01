"""004 -- server_settings table: configurable server hostname.

Revision ID: 004_server_settings
Revises: 003_domains
Create Date: 2026-03-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004_server_settings"
down_revision: str | None = "003_domains"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "server_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hostname", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("server_settings")
