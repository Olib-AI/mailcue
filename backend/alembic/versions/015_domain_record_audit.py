"""015 -- per-record DNS drift audit timestamps on domains.

Revision ID: 015_domain_record_audit
Revises: 014_tunnels
Create Date: 2026-05-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "015_domain_record_audit"
down_revision: str | None = "014_tunnels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_AUDIT_COLUMNS: tuple[str, ...] = (
    "mx_last_checked_at",
    "mx_last_verified_at",
    "spf_last_checked_at",
    "spf_last_verified_at",
    "dkim_last_checked_at",
    "dkim_last_verified_at",
    "dmarc_last_checked_at",
    "dmarc_last_verified_at",
    "mta_sts_last_checked_at",
    "mta_sts_last_verified_at",
    "tls_rpt_last_checked_at",
    "tls_rpt_last_verified_at",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col["name"] for col in inspector.get_columns("domains")}

    for name in _AUDIT_COLUMNS:
        if name not in existing:
            op.add_column(
                "domains",
                sa.Column(name, sa.DateTime(timezone=True), nullable=True),
            )


def downgrade() -> None:
    for name in reversed(_AUDIT_COLUMNS):
        op.drop_column("domains", name)
