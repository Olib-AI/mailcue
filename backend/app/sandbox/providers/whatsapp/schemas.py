"""Pydantic schemas mirroring WhatsApp Business Cloud API data structures."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TextObject(BaseModel):
    """WhatsApp text object containing the message body."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    body: str
    preview_url: bool = False


class MediaObject(BaseModel):
    """WhatsApp media object for image/document/audio messages."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    link: str | None = None
    id: str | None = None
    caption: str | None = None
    filename: str | None = None
    mime_type: str | None = None


class TemplateLanguage(BaseModel):
    """Language object for template messages."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    code: str = "en_US"


class TemplateObject(BaseModel):
    """WhatsApp template message object."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    name: str
    language: TemplateLanguage
    components: list[dict[str, Any]] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    """Request body for sending a WhatsApp message."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    messaging_product: str = "whatsapp"
    to: str
    type: str = "text"
    text: TextObject | None = None
    image: MediaObject | None = None
    document: MediaObject | None = None
    audio: MediaObject | None = None
    video: MediaObject | None = None
    template: TemplateObject | None = None


class SendMediaRequest(BaseModel):
    """Request body for sending a media message (image/document/audio)."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    messaging_product: str = "whatsapp"
    to: str
    type: str
    image: MediaObject | None = None
    document: MediaObject | None = None
    audio: MediaObject | None = None
    video: MediaObject | None = None


class MarkReadRequest(BaseModel):
    """Request body for marking a message as read."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    messaging_product: str = "whatsapp"
    status: str = "read"
    message_id: str


class SetWebhookRequest(BaseModel):
    """Request body for configuring a webhook subscription."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    url: str
    verify_token: str | None = None
