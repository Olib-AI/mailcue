"""SQLAlchemy ORM model for GPG key management."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class GpgKey(Base):
    """A GPG key associated with a mailbox address.

    Keys may be generated (``is_private=True``, full keypair) or imported
    (``is_private=False``, public key only).  The ``mailbox_address``
    column is **not** a foreign key -- it intentionally supports external
    addresses whose public keys are imported for encryption.
    """

    __tablename__ = "gpg_keys"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_uuid
    )
    mailbox_address: Mapped[str] = mapped_column(
        String(255), index=True, nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    key_id: Mapped[str] = mapped_column(String(16), nullable=False)
    uid_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uid_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    algorithm: Mapped[str | None] = mapped_column(String(32), nullable=True)
    key_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    public_key_armor: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
