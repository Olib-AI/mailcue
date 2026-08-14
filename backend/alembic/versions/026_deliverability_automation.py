"""026 -- add deliverability runs, policies, providers, and schedules.

Revision ID: 026_deliverability_automation
Revises: 025_deliverability_reports
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "026_deliverability_automation"
down_revision: str | None = "025_deliverability_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _identity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
    ]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "deliverability_runs",
        *_identity_columns(),
        sa.Column("mailbox_id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("requested_checks", sa.JSON(), nullable=False),
        sa.Column("capability_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["mailbox_id"], ["mailboxes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["deliverability_reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deliverability_runs_user_id", "deliverability_runs", ["user_id"])
    op.create_index("ix_deliverability_runs_mailbox_id", "deliverability_runs", ["mailbox_id"])
    op.create_index("ix_deliverability_runs_report_id", "deliverability_runs", ["report_id"])
    op.create_index(
        "ix_deliverability_runs_mailbox_created",
        "deliverability_runs",
        ["mailbox_id", "created_at", "id"],
    )
    op.create_index(
        "ix_deliverability_runs_status_created",
        "deliverability_runs",
        ["status", "created_at", "id"],
    )

    op.create_table(
        "deliverability_policies",
        *_identity_columns(),
        sa.Column("mailbox_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("minimum_score", sa.Integer(), nullable=False),
        sa.Column("maximum_regression", sa.Integer(), nullable=False),
        sa.Column("fail_on_statuses", sa.JSON(), nullable=False),
        sa.Column("required_check_ids", sa.JSON(), nullable=False),
        sa.Column("required_capabilities", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["mailbox_id"], ["mailboxes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mailbox_id", "name", name="uq_deliverability_policy_mailbox_name"),
    )
    op.create_index("ix_deliverability_policies_user_id", "deliverability_policies", ["user_id"])
    op.create_index(
        "ix_deliverability_policies_mailbox_id", "deliverability_policies", ["mailbox_id"]
    )
    op.create_index(
        "ix_deliverability_policies_user_enabled",
        "deliverability_policies",
        ["user_id", "enabled"],
    )

    op.create_table(
        "deliverability_policy_evaluations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("policy_id", sa.String(length=36), nullable=False),
        sa.Column("report_id", sa.String(length=36), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["deliverability_policies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["deliverability_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "policy_id", "report_id", name="uq_deliverability_policy_evaluation_report"
        ),
    )
    op.create_index(
        "ix_deliverability_policy_evaluations_policy_id",
        "deliverability_policy_evaluations",
        ["policy_id"],
    )
    op.create_index(
        "ix_deliverability_policy_evaluations_report_id",
        "deliverability_policy_evaluations",
        ["report_id"],
    )
    op.create_index(
        "ix_deliverability_policy_evaluations_created",
        "deliverability_policy_evaluations",
        ["created_at", "id"],
    )

    op.create_table(
        "deliverability_providers",
        *_identity_columns(),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("adapter", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("last_status", sa.String(length=24), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_deliverability_provider_user_name"),
    )
    op.create_index("ix_deliverability_providers_user_id", "deliverability_providers", ["user_id"])
    op.create_index(
        "ix_deliverability_providers_user_kind",
        "deliverability_providers",
        ["user_id", "kind"],
    )

    op.create_table(
        "deliverability_schedules",
        *_identity_columns(),
        sa.Column("mailbox_id", sa.String(length=36), nullable=False),
        sa.Column("policy_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("requested_checks", sa.JSON(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["mailbox_id"], ["mailboxes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["deliverability_policies.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mailbox_id", "name", name="uq_deliverability_schedule_mailbox_name"),
    )
    op.create_index("ix_deliverability_schedules_user_id", "deliverability_schedules", ["user_id"])
    op.create_index(
        "ix_deliverability_schedules_mailbox_id", "deliverability_schedules", ["mailbox_id"]
    )
    op.create_index(
        "ix_deliverability_schedules_due",
        "deliverability_schedules",
        ["enabled", "next_run_at", "id"],
    )


def downgrade() -> None:
    op.drop_table("deliverability_schedules")
    op.drop_table("deliverability_providers")
    op.drop_table("deliverability_policy_evaluations")
    op.drop_table("deliverability_policies")
    op.drop_table("deliverability_runs")
