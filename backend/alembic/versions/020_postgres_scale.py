"""020 -- relational integrity and indexes for production-scale databases.

Revision ID: 020_postgres_scale
Revises: 019_provider_aware_warmup
Create Date: 2026-07-29
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "020_postgres_scale"
down_revision: str | None = "019_provider_aware_warmup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _decode_ids(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        decoded = json.loads(value)
        return [str(item) for item in decoded]
    return [str(item) for item in value]  # type: ignore[union-attr]


def _merge_duplicate_conversations(bind: sa.Connection) -> None:
    duplicates = bind.execute(
        sa.text(
            """
            SELECT provider_id, external_id
            FROM sandbox_conversations
            GROUP BY provider_id, external_id
            HAVING COUNT(*) > 1
            """
        )
    ).all()
    for provider_id, external_id in duplicates:
        ids = (
            bind.execute(
                sa.text(
                    """
                SELECT id FROM sandbox_conversations
                WHERE provider_id = :provider_id AND external_id = :external_id
                ORDER BY created_at, id
                """
                ),
                {"provider_id": provider_id, "external_id": external_id},
            )
            .scalars()
            .all()
        )
        canonical, *redundant = ids
        for duplicate_id in redundant:
            bind.execute(
                sa.text(
                    "UPDATE sandbox_messages SET conversation_id = :canonical "
                    "WHERE conversation_id = :duplicate"
                ),
                {"canonical": canonical, "duplicate": duplicate_id},
            )
            bind.execute(
                sa.text("DELETE FROM sandbox_conversations WHERE id = :id"),
                {"id": duplicate_id},
            )


def _assert_no_rows(bind: sa.Connection, query: str, message: str) -> None:
    if bind.execute(sa.text(query)).first() is not None:
        raise RuntimeError(message)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Close schema drift that create_all-based tests previously hid.
    if "gpg_keys" not in inspector.get_table_names():
        op.create_table(
            "gpg_keys",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("mailbox_address", sa.String(255), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("key_id", sa.String(16), nullable=False),
            sa.Column("uid_name", sa.String(255), nullable=True),
            sa.Column("uid_email", sa.String(255), nullable=True),
            sa.Column("algorithm", sa.String(32), nullable=True),
            sa.Column("key_length", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("public_key_armor", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.UniqueConstraint("user_id", "fingerprint", name="uq_gpg_keys_user_fingerprint"),
        )
        op.create_index("ix_gpg_keys_mailbox_address", "gpg_keys", ["mailbox_address"])
        op.create_index("ix_gpg_keys_user_id", "gpg_keys", ["user_id"])

    campaign_columns = {column["name"] for column in inspector.get_columns("warmup_campaigns")}
    if "auto_clean_local_mailbox" not in campaign_columns:
        op.add_column(
            "warmup_campaigns",
            sa.Column(
                "auto_clean_local_mailbox",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    bind.execute(
        sa.text("UPDATE users SET is_admin = :value WHERE is_admin IS NULL"), {"value": False}
    )
    bind.execute(
        sa.text("UPDATE users SET is_active = :value WHERE is_active IS NULL"), {"value": True}
    )
    bind.execute(
        sa.text("UPDATE api_keys SET is_active = :value WHERE is_active IS NULL"), {"value": True}
    )
    bind.execute(
        sa.text("UPDATE mailboxes SET is_active = :value WHERE is_active IS NULL"), {"value": True}
    )
    bind.execute(sa.text("UPDATE mailboxes SET quota_mb = 500 WHERE quota_mb IS NULL"))

    for table_name, changes in (
        ("users", (("is_admin", sa.Boolean()), ("is_active", sa.Boolean()))),
        ("api_keys", (("is_active", sa.Boolean()),)),
        ("mailboxes", (("is_active", sa.Boolean()), ("quota_mb", sa.Integer()))),
    ):
        with op.batch_alter_table(table_name) as batch_op:
            for column_name, column_type in changes:
                batch_op.alter_column(
                    column_name,
                    existing_type=column_type,
                    nullable=False,
                )

    _merge_duplicate_conversations(bind)
    _assert_no_rows(
        bind,
        "SELECT 1 FROM forwarding_rules f LEFT JOIN users u ON u.id=f.user_id "
        "WHERE u.id IS NULL LIMIT 1",
        "Cannot add forwarding-rule ownership constraint: orphaned rules exist",
    )
    _assert_no_rows(
        bind,
        "SELECT 1 FROM warmup_events e LEFT JOIN warmup_campaigns c ON c.id=e.campaign_id "
        "WHERE c.id IS NULL LIMIT 1",
        "Cannot add warmup event constraint: orphaned campaigns exist",
    )
    _assert_no_rows(
        bind,
        "SELECT 1 FROM warmup_provider_states s "
        "LEFT JOIN warmup_campaigns c ON c.id=s.campaign_id "
        "WHERE c.id IS NULL LIMIT 1",
        "Cannot add warmup provider-state constraint: orphaned campaigns exist",
    )

    campaign_rows = bind.execute(sa.text("SELECT id, account_ids FROM warmup_campaigns")).all()
    valid_accounts = set(bind.execute(sa.text("SELECT id FROM warmup_accounts")).scalars())
    campaign_account_rows: list[tuple[str, str, int]] = []
    for campaign_id, raw_account_ids in campaign_rows:
        for position, account_id in enumerate(_decode_ids(raw_account_ids)):
            if account_id not in valid_accounts:
                raise RuntimeError(
                    f"Campaign {campaign_id} references missing warmup account {account_id}"
                )
            campaign_account_rows.append((campaign_id, account_id, position))

    # Historical account deletion was allowed for inactive campaigns. Preserve
    # their audit events while making the new account FK valid.
    bind.execute(
        sa.text(
            """
            UPDATE warmup_events SET account_id = NULL
            WHERE account_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM warmup_accounts a WHERE a.id = warmup_events.account_id
              )
            """
        )
    )

    op.create_table(
        "warmup_campaign_accounts",
        sa.Column(
            "campaign_id",
            sa.String(36),
            sa.ForeignKey("warmup_campaigns.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("warmup_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )

    for campaign_id, account_id, position in campaign_account_rows:
        bind.execute(
            sa.text(
                "INSERT INTO warmup_campaign_accounts "
                "(campaign_id, account_id, position) "
                "VALUES (:campaign_id, :account_id, :position)"
            ),
            {"campaign_id": campaign_id, "account_id": account_id, "position": position},
        )

    with op.batch_alter_table("warmup_campaigns") as batch_op:
        batch_op.drop_column("account_ids")
    with op.batch_alter_table("sandbox_conversations") as batch_op:
        batch_op.create_unique_constraint(
            "uq_sandbox_conversations_provider_external", ["provider_id", "external_id"]
        )
    with op.batch_alter_table("forwarding_rules") as batch_op:
        batch_op.create_foreign_key(
            "fk_forwarding_rules_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="CASCADE",
        )
    with op.batch_alter_table("warmup_events") as batch_op:
        batch_op.create_foreign_key(
            "fk_warmup_events_campaign_id_campaigns",
            "warmup_campaigns",
            ["campaign_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_warmup_events_account_id_accounts",
            "warmup_accounts",
            ["account_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("warmup_provider_states") as batch_op:
        batch_op.create_foreign_key(
            "fk_warmup_provider_states_campaign_id_campaigns",
            "warmup_campaigns",
            ["campaign_id"],
            ["id"],
            ondelete="CASCADE",
        )

    indexes: tuple[tuple[str, str, list[str]], ...] = (
        ("ix_sandbox_providers_user_type", "sandbox_providers", ["user_id", "provider_type"]),
        (
            "ix_sandbox_messages_provider_created",
            "sandbox_messages",
            ["provider_id", "created_at", "id"],
        ),
        (
            "ix_sandbox_messages_conversation_created",
            "sandbox_messages",
            ["conversation_id", "created_at", "id"],
        ),
        (
            "ix_sandbox_webhook_endpoints_provider_active",
            "sandbox_webhook_endpoints",
            ["provider_id", "is_active"],
        ),
        (
            "ix_sandbox_webhook_deliveries_endpoint_created",
            "sandbox_webhook_deliveries",
            ["endpoint_id", "created_at", "id"],
        ),
        ("ix_httpbin_bins_user_created", "httpbin_bins", ["user_id", "created_at"]),
        ("ix_httpbin_requests_bin_created", "httpbin_requests", ["bin_id", "created_at", "id"]),
        ("ix_forwarding_rules_user_created", "forwarding_rules", ["user_id", "created_at"]),
        (
            "ix_sandbox_calls_provider_created",
            "sandbox_calls",
            ["provider_id", "created_at", "id"],
        ),
        ("ix_sandbox_calls_provider_external", "sandbox_calls", ["provider_id", "external_id"]),
        (
            "ix_sandbox_phone_numbers_provider_created",
            "sandbox_phone_numbers",
            ["provider_id", "created_at", "id"],
        ),
        (
            "ix_sandbox_phone_numbers_provider_external",
            "sandbox_phone_numbers",
            ["provider_id", "external_id"],
        ),
        (
            "ix_sandbox_phone_numbers_provider_e164",
            "sandbox_phone_numbers",
            ["provider_id", "e164"],
        ),
        (
            "ix_sandbox_number_orders_provider_external",
            "sandbox_number_orders",
            ["provider_id", "external_id"],
        ),
        (
            "ix_sandbox_port_requests_provider_external",
            "sandbox_port_requests",
            ["provider_id", "external_id"],
        ),
        ("ix_sandbox_brands_provider_external", "sandbox_brands", ["provider_id", "external_id"]),
        (
            "ix_sandbox_campaigns_provider_external",
            "sandbox_campaigns",
            ["provider_id", "external_id"],
        ),
        (
            "ix_warmup_campaigns_status_next_run",
            "warmup_campaigns",
            ["status", "next_run_at", "id"],
        ),
        (
            "ix_warmup_events_campaign_account_status_created",
            "warmup_events",
            ["campaign_id", "account_id", "status", "created_at"],
        ),
    )
    for name, table, columns in indexes:
        op.create_index(name, table, columns)


def downgrade() -> None:
    bind = op.get_bind()
    indexes = (
        ("ix_warmup_events_campaign_account_status_created", "warmup_events"),
        ("ix_warmup_campaigns_status_next_run", "warmup_campaigns"),
        ("ix_sandbox_campaigns_provider_external", "sandbox_campaigns"),
        ("ix_sandbox_brands_provider_external", "sandbox_brands"),
        ("ix_sandbox_port_requests_provider_external", "sandbox_port_requests"),
        ("ix_sandbox_number_orders_provider_external", "sandbox_number_orders"),
        ("ix_sandbox_phone_numbers_provider_e164", "sandbox_phone_numbers"),
        ("ix_sandbox_phone_numbers_provider_external", "sandbox_phone_numbers"),
        ("ix_sandbox_phone_numbers_provider_created", "sandbox_phone_numbers"),
        ("ix_sandbox_calls_provider_external", "sandbox_calls"),
        ("ix_sandbox_calls_provider_created", "sandbox_calls"),
        ("ix_forwarding_rules_user_created", "forwarding_rules"),
        ("ix_httpbin_requests_bin_created", "httpbin_requests"),
        ("ix_httpbin_bins_user_created", "httpbin_bins"),
        ("ix_sandbox_webhook_deliveries_endpoint_created", "sandbox_webhook_deliveries"),
        ("ix_sandbox_webhook_endpoints_provider_active", "sandbox_webhook_endpoints"),
        ("ix_sandbox_messages_conversation_created", "sandbox_messages"),
        ("ix_sandbox_messages_provider_created", "sandbox_messages"),
        ("ix_sandbox_providers_user_type", "sandbox_providers"),
    )
    for name, table in indexes:
        op.drop_index(name, table_name=table)

    with op.batch_alter_table("warmup_provider_states") as batch_op:
        batch_op.drop_constraint(
            "fk_warmup_provider_states_campaign_id_campaigns", type_="foreignkey"
        )
    with op.batch_alter_table("warmup_events") as batch_op:
        batch_op.drop_constraint("fk_warmup_events_account_id_accounts", type_="foreignkey")
        batch_op.drop_constraint("fk_warmup_events_campaign_id_campaigns", type_="foreignkey")
    with op.batch_alter_table("forwarding_rules") as batch_op:
        batch_op.drop_constraint("fk_forwarding_rules_user_id_users", type_="foreignkey")
    with op.batch_alter_table("sandbox_conversations") as batch_op:
        batch_op.drop_constraint("uq_sandbox_conversations_provider_external", type_="unique")

    with op.batch_alter_table("warmup_campaigns") as batch_op:
        batch_op.add_column(
            sa.Column("account_ids", sa.JSON(), nullable=False, server_default="[]")
        )
    rows = bind.execute(
        sa.text(
            "SELECT campaign_id, account_id FROM warmup_campaign_accounts "
            "ORDER BY campaign_id, position"
        )
    ).all()
    by_campaign: dict[str, list[str]] = {}
    for campaign_id, account_id in rows:
        by_campaign.setdefault(campaign_id, []).append(account_id)
    for campaign_id, account_ids in by_campaign.items():
        value: object = account_ids
        if bind.dialect.name == "sqlite":
            value = json.dumps(account_ids)
        bind.execute(
            sa.text("UPDATE warmup_campaigns SET account_ids=:ids WHERE id=:id"),
            {"ids": value, "id": campaign_id},
        )
    op.drop_table("warmup_campaign_accounts")
    op.drop_column("warmup_campaigns", "auto_clean_local_mailbox")
    op.drop_index("ix_gpg_keys_mailbox_address", table_name="gpg_keys")
    op.drop_table("gpg_keys")

    for table_name, changes in (
        ("users", (("is_admin", sa.Boolean()), ("is_active", sa.Boolean()))),
        ("api_keys", (("is_active", sa.Boolean()),)),
        ("mailboxes", (("is_active", sa.Boolean()), ("quota_mb", sa.Integer()))),
    ):
        with op.batch_alter_table(table_name) as batch_op:
            for column_name, column_type in changes:
                batch_op.alter_column(
                    column_name,
                    existing_type=column_type,
                    nullable=True,
                )
