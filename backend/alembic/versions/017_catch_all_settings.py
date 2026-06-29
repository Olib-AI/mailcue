"""017 -- catch_all settings: catch_all_enabled for server_settings and is_catchall for mailboxes.

Revision ID: 017_catch_all_settings
Revises: 016_api_key_permissions
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "017_catch_all_settings"
down_revision: str | None = "016_api_key_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column in [c["name"] for c in inspector.get_columns(table)]


def upgrade() -> None:
    if not _column_exists("server_settings", "catch_all_enabled"):
        op.add_column(
            "server_settings",
            sa.Column(
                "catch_all_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")
            ),
        )
    if not _column_exists("mailboxes", "is_catchall"):
        op.add_column(
            "mailboxes",
            sa.Column("is_catchall", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )


def downgrade() -> None:
    with op.batch_alter_table("mailboxes") as batch_op:
        batch_op.drop_column("is_catchall")
    with op.batch_alter_table("server_settings") as batch_op:
        batch_op.drop_column("catch_all_enabled")
