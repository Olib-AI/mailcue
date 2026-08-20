"""Persistence for tenant-scoped email-validation delivery feedback."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EmailValidationFeedback(Base):
    """One organic delivery outcome used to calibrate catch-all risk."""

    __tablename__ = "email_validation_feedback"
    __table_args__ = (
        Index("ix_validation_feedback_user_email_time", "user_id", "email_hash", "occurred_at"),
        Index("ix_validation_feedback_user_domain_time", "user_id", "domain", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    smtp_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enhanced_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
