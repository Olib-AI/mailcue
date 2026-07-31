"""023 -- reset cached MTA-STS verification after endpoint checks were added.

Revision ID: 023_reset_mta_sts_verification
Revises: 022_gpg_tenant_ownership
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "023_reset_mta_sts_verification"
down_revision: str | None = "022_gpg_tenant_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    domains = sa.table(
        "domains",
        sa.column("mta_sts_verified", sa.Boolean()),
    )
    op.execute(domains.update().values(mta_sts_verified=False))


def downgrade() -> None:
    # The old TXT-only result cannot be reconstructed safely.
    pass
