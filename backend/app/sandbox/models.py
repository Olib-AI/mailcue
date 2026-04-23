"""SQLAlchemy ORM models for the messaging sandbox."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class SandboxProvider(Base):
    """A messaging provider configuration owned by a user."""

    __tablename__ = "sandbox_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    credentials: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    conversations: Mapped[list[SandboxConversation]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )
    webhook_endpoints: Mapped[list[SandboxWebhookEndpoint]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )


class SandboxConversation(Base):
    """A conversation thread within a provider."""

    __tablename__ = "sandbox_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sandbox_providers.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    conversation_type: Mapped[str] = mapped_column(String(50), default="direct", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # type: ignore[assignment]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    messages: Mapped[list[SandboxMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    provider: Mapped[SandboxProvider] = relationship(back_populates="conversations")


class SandboxMessage(Base):
    """An individual message passing through the sandbox."""

    __tablename__ = "sandbox_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sandbox_providers.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("sandbox_conversations.id", ondelete="CASCADE"),
        nullable=True,
    )
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    sender: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(String(50), default="text", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_request: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # type: ignore[assignment]
    raw_response: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # type: ignore[assignment]
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # type: ignore[assignment]
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    conversation: Mapped[SandboxConversation | None] = relationship(back_populates="messages")


class SandboxWebhookEndpoint(Base):
    """A webhook URL registered to receive sandbox events."""

    __tablename__ = "sandbox_webhook_endpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sandbox_providers.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_types: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # type: ignore[assignment]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    provider: Mapped[SandboxProvider] = relationship(back_populates="webhook_endpoints")
    deliveries: Mapped[list[SandboxWebhookDelivery]] = relationship(
        back_populates="endpoint", cascade="all, delete-orphan"
    )


class SandboxWebhookDelivery(Base):
    """Record of a webhook delivery attempt."""

    __tablename__ = "sandbox_webhook_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    endpoint_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sandbox_webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("sandbox_messages.id", ondelete="CASCADE"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # type: ignore[assignment]
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    endpoint: Mapped[SandboxWebhookEndpoint] = relationship(back_populates="deliveries")


class SandboxCall(Base):
    """A simulated voice call."""

    __tablename__ = "sandbox_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sandbox_providers.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="outbound")
    from_number: Mapped[str] = mapped_column(String(32), nullable=False)
    to_number: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    answer_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    answer_method: Mapped[str] = mapped_column(String(8), nullable=False, default="POST")
    status_callback: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status_callback_method: Mapped[str] = mapped_column(String(8), nullable=False, default="POST")
    record: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    price: Mapped[str | None] = mapped_column(String(32), nullable=True)
    price_unit: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    raw_request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    transcript_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class SandboxPhoneNumber(Base):
    """A phone number that has been purchased in the sandbox."""

    __tablename__ = "sandbox_phone_numbers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sandbox_providers.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    e164: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    iso_country: Mapped[str] = mapped_column(String(4), nullable=False, default="US")
    number_type: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    locality: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sms_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sms_method: Mapped[str] = mapped_column(String(8), nullable=False, default="POST")
    voice_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    voice_method: Mapped[str] = mapped_column(String(8), nullable=False, default="POST")
    status_callback: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    raw_request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    released: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class SandboxNumberOrder(Base):
    """A request to purchase one or more phone numbers."""

    __tablename__ = "sandbox_number_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sandbox_providers.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    numbers: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    raw_request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class SandboxPortRequest(Base):
    """A number porting order."""

    __tablename__ = "sandbox_port_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sandbox_providers.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="submitted")
    numbers: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    loa_info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    raw_request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    foc_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class SandboxBrand(Base):
    """An A2P 10DLC brand registration."""

    __tablename__ = "sandbox_brands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sandbox_providers.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    ein: Mapped[str | None] = mapped_column(String(50), nullable=True)
    brand_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    raw_request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class SandboxCampaign(Base):
    """An A2P 10DLC campaign registration."""

    __tablename__ = "sandbox_campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sandbox_providers.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sandbox_brands.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    use_case: Mapped[str] = mapped_column(String(64), nullable=False, default="MIXED")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_messages: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    raw_request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
