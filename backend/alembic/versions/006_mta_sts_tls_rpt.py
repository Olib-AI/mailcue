"""006 -- add MTA-STS and TLS-RPT verification columns to domains.

Revision ID: 006_mta_sts_tls_rpt
Revises: 005_tls_certificates
Create Date: 2026-03-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "006_mta_sts_tls_rpt"
down_revision: str | None = "005_tls_certificates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "domains",
        sa.Column("mta_sts_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "domains",
        sa.Column("tls_rpt_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("domains", "tls_rpt_verified")
    op.drop_column("domains", "mta_sts_verified")
