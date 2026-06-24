"""Pydantic v2 schemas for the messaging sandbox API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ProviderCreateRequest(BaseModel):
    provider_type: str
    name: str
    credentials: dict[str, Any] = {}


class ProviderUpdateRequest(BaseModel):
    name: str | None = None
    credentials: dict[str, Any] | None = None
    is_active: bool | None = None


class ProviderResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    user_id: str
    provider_type: str
    name: str
    credentials: dict[str, Any]
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
    metadata_json: dict[str, Any]
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
    raw_request: dict[str, Any]
    raw_response: dict[str, Any]
    metadata_json: dict[str, Any]
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
    metadata: dict[str, Any] = {}
    conversation_name: str | None = None


class SendRequest(BaseModel):
    sender: str = "User"
    content: str
    content_type: str = "text"
    conversation_id: str | None = None
    conversation_name: str | None = None
    metadata: dict[str, Any] = {}


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
    event_types: list[str]
    is_active: bool
    created_at: datetime


class WebhookDeliveryResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    endpoint_id: str
    message_id: str | None = None
    event_type: str
    payload: dict[str, Any]
    status_code: int | None = None
    response_body: str | None = None
    attempt: int
    delivered_at: datetime | None = None
    created_at: datetime
