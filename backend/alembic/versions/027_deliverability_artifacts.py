"""027 -- add tenant-protected deliverability artifacts.

Revision ID: 027_deliverability_artifacts
Revises: 026_deliverability_automation
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "027_deliverability_artifacts"
down_revision: str | None = "026_deliverability_automation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deliverability_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=127), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["deliverability_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deliverability_artifacts_user_id", "deliverability_artifacts", ["user_id"])
    op.create_index("ix_deliverability_artifacts_run_id", "deliverability_artifacts", ["run_id"])
    op.create_index(
        "ix_deliverability_artifacts_run_created",
        "deliverability_artifacts",
        ["run_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_table("deliverability_artifacts")
