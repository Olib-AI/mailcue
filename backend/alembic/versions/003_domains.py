"""003 -- domains table: managed email domains with DKIM and DNS verification.

Revision ID: 003_domains
Revises: 002_auth_security
Create Date: 2026-02-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003_domains"
down_revision: str | None = "002_auth_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "domains",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), unique=True, index=True, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dkim_selector", sa.String(100), nullable=False, server_default="mail"),
        sa.Column("dkim_private_key_path", sa.String(500), nullable=True),
        sa.Column("dkim_public_key_txt", sa.String(2000), nullable=True),
        sa.Column("mx_verified", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("spf_verified", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("dkim_verified", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("dmarc_verified", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("last_dns_check", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("domains")
