"""SQLAlchemy ORM model for managed email domains."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Domain(Base):
    """An email domain managed by MailCue with DKIM keys and DNS verification."""

    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # ── DKIM ──────────────────────────────────────────────────────
    dkim_selector: Mapped[str] = mapped_column(String(100), default="mail")
    dkim_private_key_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dkim_public_key_txt: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # ── DNS verification cache ────────────────────────────────────
    mx_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    spf_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    dkim_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    dmarc_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_dns_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
