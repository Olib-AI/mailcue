"""SQLAlchemy ORM models for server-wide settings and TLS certificates."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ServerSettings(Base):
    """Single-row table holding server-wide configuration."""

    __tablename__ = "server_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)


class TlsCertificate(Base):
    """Single-row table holding the custom TLS certificate and key."""

    __tablename__ = "tls_certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    certificate_pem: Mapped[str] = mapped_column(Text, nullable=False)
    private_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    ca_certificate_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Extracted metadata (populated at upload time)
    common_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    san_dns_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    not_before: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    not_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fingerprint_sha256: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
