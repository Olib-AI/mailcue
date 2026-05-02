"""014 -- create tunnels and tunnel_client_identity tables.

Revision ID: 014_tunnels
Revises: 013_phone_sandbox
Create Date: 2026-05-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "014_tunnels"
down_revision: str | None = "013_phone_sandbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "tunnels" not in existing:
        op.create_table(
            "tunnels",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(120), unique=True, nullable=False),
            sa.Column("endpoint_host", sa.String(255), nullable=False),
            sa.Column("endpoint_port", sa.Integer(), nullable=False),
            sa.Column("server_pubkey", sa.String(64), nullable=False),
            sa.Column(
                "enabled",
                sa.Boolean(),
                server_default=sa.text("1"),
                nullable=False,
            ),
            sa.Column(
                "weight",
                sa.Integer(),
                server_default=sa.text("1"),
                nullable=False,
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(), nullable=True),
            sa.Column("last_check_ok", sa.Boolean(), nullable=True),
            sa.Column("last_check_message", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    if "tunnel_client_identity" not in existing:
        op.create_table(
            "tunnel_client_identity",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("public_key", sa.String(64), nullable=True),
            sa.Column("fingerprint", sa.String(64), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("tunnel_client_identity")
    op.drop_table("tunnels")
