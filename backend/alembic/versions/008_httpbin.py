"""008 -- create HTTP Bin tables.

Revision ID: 008_httpbin
Revises: 007_sandbox
Create Date: 2026-03-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008_httpbin"
down_revision: str | None = "007_sandbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "httpbin_bins",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("response_status_code", sa.Integer, nullable=False, server_default="200"),
        sa.Column("response_body", sa.Text, nullable=True, server_default=""),
        sa.Column(
            "response_content_type",
            sa.String(100),
            nullable=False,
            server_default="application/json",
        ),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "httpbin_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "bin_id",
            sa.String(36),
            sa.ForeignKey("httpbin_bins.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("path", sa.String(2000), nullable=False, server_default="/"),
        sa.Column("headers", sa.JSON, nullable=False),
        sa.Column("query_params", sa.JSON, nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("content_type", sa.String(200), nullable=True),
        sa.Column("remote_addr", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("httpbin_requests")
    op.drop_table("httpbin_bins")
