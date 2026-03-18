"""SQLAlchemy ORM model for email forwarding rules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class ForwardingRule(Base):
    """A user-defined rule that matches incoming emails and forwards them.

    Matching is performed via regex patterns against the ``From``, ``To``,
    and ``Subject`` headers, and optionally restricted to a specific mailbox.
    When a match occurs the configured action is executed: either relaying
    via SMTP (``smtp_forward``) or POSTing the email data to a webhook URL.
    """

    __tablename__ = "forwarding_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Match patterns (regex, all optional -- a rule with no patterns matches everything)
    match_from: Mapped[str | None] = mapped_column(String(500), nullable=True)
    match_to: Mapped[str | None] = mapped_column(String(500), nullable=True)
    match_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    match_mailbox: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Action: "smtp_forward" or "webhook"
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # JSON-encoded action configuration.
    # smtp_forward: {"to_address": "user@example.com"}
    # webhook:      {"url": "https://...", "method": "POST", "headers": {...}}
    action_config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
