"""Persistence models for warmup accounts, campaigns, and delivery history."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WarmupAccount(Base):
    """An external mailbox controlled by the administrator."""

    __tablename__ = "warmup_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="custom")
    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    smtp_security: Mapped[str] = mapped_column(String(12), nullable=False, default="starttls")
    imap_host: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, nullable=False, default=993)
    imap_security: Mapped[str] = mapped_column(String(12), nullable=False, default="ssl")
    username: Mapped[str] = mapped_column(String(320), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("1"))
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("0"))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=sa.func.now())


class WarmupCampaign(Base):
    """A gradual, rate-capped warmup plan for one local sender."""

    __tablename__ = "warmup_campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    local_address: Mapped[str] = mapped_column(String(320), nullable=False)
    account_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    start_daily_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    daily_ramp: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_daily_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    min_delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    max_delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    reply_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=70)
    active_hour_start: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    active_hour_end: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    messages_sent_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    volume_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=sa.func.now())


class WarmupEvent(Base):
    """Audit record for each scheduler attempt."""

    __tablename__ = "warmup_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    direction: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enhanced_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=sa.func.now())


class WarmupProviderState(Base):
    """Per-campaign receiving-provider pacing and delivery health."""

    __tablename__ = "warmup_provider_states"
    __table_args__ = (UniqueConstraint("campaign_id", "provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="healthy")
    sent_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    volume_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_smtp_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_enhanced_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=sa.func.now())
