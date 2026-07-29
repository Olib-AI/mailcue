"""022 -- tenant ownership for GPG keys.

Revision ID: 022_gpg_tenant_ownership
Revises: 021_session_revocation
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "022_gpg_tenant_ownership"
down_revision: str | None = "021_session_revocation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("gpg_keys")}
    naming = {"uq": "uq_%(table_name)s_%(column_0_name)s"}

    if "user_id" not in columns:
        with op.batch_alter_table("gpg_keys", naming_convention=naming) as batch_op:
            batch_op.add_column(sa.Column("user_id", sa.String(36), nullable=True))
            batch_op.create_foreign_key(
                "fk_gpg_keys_user_id_users",
                "users",
                ["user_id"],
                ["id"],
                ondelete="CASCADE",
            )

    # Preserve ownership for private keys and keys already associated with a
    # local mailbox. Ambiguous legacy external keys remain inaccessible until
    # a user explicitly imports them again.
    bind.execute(
        sa.text(
            """
            UPDATE gpg_keys
            SET user_id = (
                SELECT mailboxes.user_id FROM mailboxes
                WHERE lower(mailboxes.address) = lower(gpg_keys.mailbox_address)
            )
            WHERE user_id IS NULL
            """
        )
    )

    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints("gpg_keys")
    fingerprint_only = next(
        (
            constraint
            for constraint in unique_constraints
            if constraint.get("column_names") == ["fingerprint"]
        ),
        None,
    )
    composite_exists = any(
        set(constraint.get("column_names") or []) == {"user_id", "fingerprint"}
        for constraint in unique_constraints
    )
    with op.batch_alter_table("gpg_keys", naming_convention=naming) as batch_op:
        if fingerprint_only is not None:
            batch_op.drop_constraint(
                fingerprint_only.get("name") or "uq_gpg_keys_fingerprint",
                type_="unique",
            )
        if not composite_exists:
            batch_op.create_unique_constraint(
                "uq_gpg_keys_user_fingerprint", ["user_id", "fingerprint"]
            )

    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("gpg_keys")}
    if "ix_gpg_keys_user_id" not in indexes:
        op.create_index("ix_gpg_keys_user_id", "gpg_keys", ["user_id"])


def downgrade() -> None:
    with op.batch_alter_table("gpg_keys") as batch_op:
        batch_op.drop_constraint("uq_gpg_keys_user_fingerprint", type_="unique")
        batch_op.create_unique_constraint("uq_gpg_keys_fingerprint", ["fingerprint"])
    op.drop_index("ix_gpg_keys_user_id", table_name="gpg_keys")
    with op.batch_alter_table("gpg_keys") as batch_op:
        batch_op.drop_column("user_id")
