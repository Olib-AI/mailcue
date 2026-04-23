"""013 -- phone-provider sandbox tables (calls, numbers, port, brand, campaign).

Revision ID: 013_phone_sandbox
Revises: 012_multi_user
Create Date: 2026-04-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "013_phone_sandbox"
down_revision: str | None = "012_multi_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sandbox_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("sandbox_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False, server_default="outbound"),
        sa.Column("from_number", sa.String(32), nullable=False),
        sa.Column("to_number", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("answer_url", sa.String(1024), nullable=True),
        sa.Column("answer_method", sa.String(8), nullable=False, server_default="POST"),
        sa.Column("status_callback", sa.String(1024), nullable=True),
        sa.Column("status_callback_method", sa.String(8), nullable=False, server_default="POST"),
        sa.Column("record", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("price", sa.String(32), nullable=True),
        sa.Column("price_unit", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("raw_request", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("transcript_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sandbox_calls_external_id", "sandbox_calls", ["external_id"])

    op.create_table(
        "sandbox_phone_numbers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("sandbox_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("e164", sa.String(32), nullable=False),
        sa.Column("iso_country", sa.String(4), nullable=False, server_default="US"),
        sa.Column("number_type", sa.String(16), nullable=False, server_default="local"),
        sa.Column("locality", sa.String(100), nullable=True),
        sa.Column("region", sa.String(50), nullable=True),
        sa.Column("sms_url", sa.String(1024), nullable=True),
        sa.Column("sms_method", sa.String(8), nullable=False, server_default="POST"),
        sa.Column("voice_url", sa.String(1024), nullable=True),
        sa.Column("voice_method", sa.String(8), nullable=False, server_default="POST"),
        sa.Column("status_callback", sa.String(1024), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("raw_request", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("released", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_sandbox_phone_numbers_external_id", "sandbox_phone_numbers", ["external_id"]
    )
    op.create_index("ix_sandbox_phone_numbers_e164", "sandbox_phone_numbers", ["e164"])

    op.create_table(
        "sandbox_number_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("sandbox_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("numbers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("raw_request", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_sandbox_number_orders_external_id", "sandbox_number_orders", ["external_id"]
    )

    op.create_table(
        "sandbox_port_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("sandbox_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="submitted"),
        sa.Column("numbers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("loa_info", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("raw_request", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("foc_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_sandbox_port_requests_external_id", "sandbox_port_requests", ["external_id"]
    )

    op.create_table(
        "sandbox_brands",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("sandbox_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("company_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("ein", sa.String(50), nullable=True),
        sa.Column("brand_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("raw_request", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sandbox_brands_external_id", "sandbox_brands", ["external_id"])

    op.create_table(
        "sandbox_campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider_id",
            sa.String(36),
            sa.ForeignKey("sandbox_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "brand_id",
            sa.String(36),
            sa.ForeignKey("sandbox_brands.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("use_case", sa.String(64), nullable=False, server_default="MIXED"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sample_messages", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("raw_request", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sandbox_campaigns_external_id", "sandbox_campaigns", ["external_id"])


def downgrade() -> None:
    op.drop_index("ix_sandbox_campaigns_external_id", table_name="sandbox_campaigns")
    op.drop_table("sandbox_campaigns")
    op.drop_index("ix_sandbox_brands_external_id", table_name="sandbox_brands")
    op.drop_table("sandbox_brands")
    op.drop_index("ix_sandbox_port_requests_external_id", table_name="sandbox_port_requests")
    op.drop_table("sandbox_port_requests")
    op.drop_index("ix_sandbox_number_orders_external_id", table_name="sandbox_number_orders")
    op.drop_table("sandbox_number_orders")
    op.drop_index("ix_sandbox_phone_numbers_e164", table_name="sandbox_phone_numbers")
    op.drop_index("ix_sandbox_phone_numbers_external_id", table_name="sandbox_phone_numbers")
    op.drop_table("sandbox_phone_numbers")
    op.drop_index("ix_sandbox_calls_external_id", table_name="sandbox_calls")
    op.drop_table("sandbox_calls")
