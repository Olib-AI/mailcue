"""SQLAlchemy ORM model for mailboxes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.auth.models import User

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Mailbox(Base):
    """A virtual mailbox managed by Dovecot.

    Each record corresponds to a line in the Dovecot ``passwd-file``
    and a Maildir directory on disk.
    """

    __tablename__ = "mailboxes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    address: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    domain: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    quota_mb: Mapped[int] = mapped_column(Integer, default=500)
    signature: Mapped[str] = mapped_column(Text, default="", server_default="")

    # ── Ownership ───────────────────────────────────────────────
    user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    owner: Mapped[User | None] = relationship(
        "User", back_populates="mailboxes", foreign_keys=[user_id]
    )
