"""SQLAlchemy ORM models for SMTP egress tunnels.

These tables drive the ``mailcue-relay-sidecar`` Rust binary, which reads
``/etc/mailcue-sidecar/tunnels.json`` and relays outbound SMTP through one
or more remote VPS edges over a Noise IK encrypted protocol.  This module
manages the *control plane* only -- it does NOT handle the relay traffic.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Tunnel(Base):
    """A configured outbound SMTP relay tunnel pointing at a remote edge."""

    __tablename__ = "tunnels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    endpoint_host: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint_port: Mapped[int] = mapped_column(Integer, nullable=False, default=7843)
    server_pubkey: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=sa.text("1"), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, server_default=sa.text("1"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Health (set by ``POST /api/v1/tunnels/{id}/check``)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_check_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=sa.func.now(), nullable=False
    )


class TunnelClientIdentity(Base):
    """Single-row table holding the Mailcue side's long-term tunnel client pubkey.

    The API displays this so the admin can copy it into the edge's
    ``authorized_clients`` allow-list.  The actual private key lives only on
    the sidecar's filesystem -- we never store it here.
    """

    __tablename__ = "tunnel_client_identity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    public_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
