"""Pydantic v2 schemas for the messaging sandbox API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ProviderCreateRequest(BaseModel):
    provider_type: str
    name: str
    credentials: dict = {}  # type: ignore[assignment]


class ProviderUpdateRequest(BaseModel):
    name: str | None = None
    credentials: dict | None = None  # type: ignore[assignment]
    is_active: bool | None = None


class ProviderResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    provider_type: str
    name: str
    credentials: dict  # type: ignore[assignment]
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None


class ConversationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    provider_id: str
    external_id: str
    name: str | None = None
    conversation_type: str
    metadata_json: dict  # type: ignore[assignment]
    created_at: datetime


class MessageResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    provider_id: str
    conversation_id: str | None = None
    direction: str
    sender: str
    content: str | None = None
    content_type: str
    external_id: str | None = None
    raw_request: dict  # type: ignore[assignment]
    raw_response: dict  # type: ignore[assignment]
    metadata_json: dict  # type: ignore[assignment]
    is_deleted: bool
    created_at: datetime


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int


class SimulateRequest(BaseModel):
    sender: str
    content: str
    content_type: str = "text"
    conversation_id: str | None = None
    metadata: dict = {}  # type: ignore[assignment]
    conversation_name: str | None = None


class SendRequest(BaseModel):
    sender: str = "User"
    content: str
    content_type: str = "text"
    conversation_id: str | None = None
    conversation_name: str | None = None
    metadata: dict = {}  # type: ignore[assignment]


class WebhookEndpointCreateRequest(BaseModel):
    url: str
    secret: str | None = None
    event_types: list[str] = []


class WebhookEndpointResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    provider_id: str
    url: str
    secret: str | None = None
    event_types: list[str]  # type: ignore[assignment]
    is_active: bool
    created_at: datetime


class WebhookDeliveryResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    endpoint_id: str
    message_id: str | None = None
    event_type: str
    payload: dict  # type: ignore[assignment]
    status_code: int | None = None
    response_body: str | None = None
    attempt: int
    delivered_at: datetime | None = None
    created_at: datetime
