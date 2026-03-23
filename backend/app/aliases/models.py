"""SQLAlchemy ORM model for email aliases."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Alias(Base):
    """An email alias that maps a source address to a destination address.

    Supports catch-all aliases where the source is ``@domain.com`` and
    ``is_catchall`` is ``True``.
    """

    __tablename__ = "aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_address: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    destination_address: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(255), index=True)
    is_catchall: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=_utcnow
    )
