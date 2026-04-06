"""012 -- multi-user support: mailbox ownership and per-user quota.

Revision ID: 012_multi_user
Revises: 011_aliases
Create Date: 2026-04-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "012_multi_user"
down_revision: str | None = "011_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table: str, column: str) -> bool:
    """Check if a column already exists in a table (idempotency guard)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    # ── users.max_mailboxes ─────────────────────────────────────
    if not _column_exists("users", "max_mailboxes"):
        op.add_column(
            "users",
            sa.Column("max_mailboxes", sa.Integer(), nullable=False, server_default="5"),
        )

    # ── mailboxes.user_id ───────────────────────────────────────
    if not _column_exists("mailboxes", "user_id"):
        op.add_column(
            "mailboxes",
            sa.Column("user_id", sa.String(36), nullable=True),
        )
        # SQLite doesn't support ADD CONSTRAINT, so we create the FK
        # via naming convention. For SQLite the FK is advisory; the
        # relationship is enforced at the ORM level.
        with op.batch_alter_table("mailboxes") as batch_op:
            batch_op.create_index("ix_mailboxes_user_id", ["user_id"])
            batch_op.create_foreign_key(
                "fk_mailboxes_user_id_users",
                "users",
                ["user_id"],
                ["id"],
                ondelete="SET NULL",
            )

    # ── Data migration: assign orphan mailboxes to first admin ──
    bind = op.get_bind()
    result = bind.execute(
        sa.text("SELECT id FROM users WHERE is_admin = 1 ORDER BY created_at LIMIT 1")
    )
    row = result.fetchone()
    if row is not None:
        admin_id = row[0]
        bind.execute(
            sa.text("UPDATE mailboxes SET user_id = :admin_id WHERE user_id IS NULL"),
            {"admin_id": admin_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("mailboxes") as batch_op:
        batch_op.drop_constraint("fk_mailboxes_user_id_users", type_="foreignkey")
        batch_op.drop_index("ix_mailboxes_user_id")
        batch_op.drop_column("user_id")

    op.drop_column("users", "max_mailboxes")
