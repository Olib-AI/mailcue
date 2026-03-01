"""005 -- tls_certificates table: custom TLS certificate storage.

Revision ID: 005_tls_certificates
Revises: 004_server_settings
Create Date: 2026-03-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "005_tls_certificates"
down_revision: str | None = "004_server_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tls_certificates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("certificate_pem", sa.Text(), nullable=False),
        sa.Column("private_key_pem", sa.Text(), nullable=False),
        sa.Column("ca_certificate_pem", sa.Text(), nullable=True),
        sa.Column("common_name", sa.String(255), nullable=True),
        sa.Column("san_dns_names", sa.JSON(), nullable=True),
        sa.Column("not_before", sa.DateTime(), nullable=True),
        sa.Column("not_after", sa.DateTime(), nullable=True),
        sa.Column("fingerprint_sha256", sa.String(255), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tls_certificates")
