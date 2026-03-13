"""SQLAlchemy ORM models for the built-in HTTP Bin."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class HttpBinBin(Base):
    """A request-capture bin owned by a user."""

    __tablename__ = "httpbin_bins"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    response_status_code: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    response_content_type: Mapped[str] = mapped_column(
        String(100), default="application/json", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    requests: Mapped[list[HttpBinRequest]] = relationship(
        back_populates="bin", cascade="all, delete-orphan"
    )


class HttpBinRequest(Base):
    """A captured HTTP request to a bin."""

    __tablename__ = "httpbin_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    bin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("httpbin_bins.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(2000), default="/", nullable=False)
    headers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # type: ignore[assignment]
    query_params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # type: ignore[assignment]
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    remote_addr: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    bin: Mapped[HttpBinBin] = relationship(back_populates="requests")
