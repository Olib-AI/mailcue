"""Pydantic schemas mirroring Telegram Bot API data structures."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TelegramUser(BaseModel):
    """Telegram User object."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: int
    is_bot: bool
    first_name: str
    username: str | None = None


class TelegramChat(BaseModel):
    """Telegram Chat object."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: int
    type: str = "private"
    title: str | None = None
    username: str | None = None
    first_name: str | None = None


class TelegramMessage(BaseModel):
    """Telegram Message object."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    message_id: int
    from_: TelegramUser | None = Field(default=None, alias="from")
    chat: TelegramChat
    date: int
    text: str | None = None
    edit_date: int | None = None


class TelegramResponse(BaseModel):
    """Standard Telegram Bot API response envelope."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    ok: bool = True
    result: Any = None


class SendMessageRequest(BaseModel):
    """Request body for sendMessage."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    chat_id: int | str
    text: str
    parse_mode: str | None = None
    reply_markup: dict[str, Any] | None = None


class EditMessageRequest(BaseModel):
    """Request body for editMessageText."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    chat_id: int | str
    message_id: int
    text: str


class DeleteMessageRequest(BaseModel):
    """Request body for deleteMessage."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    chat_id: int | str
    message_id: int


class SetWebhookRequest(BaseModel):
    """Request body for setWebhook."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    url: str
    secret_token: str | None = None


class GetUpdatesRequest(BaseModel):
    """Request body for getUpdates."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    offset: int | None = None
    limit: int = 100
    timeout: int = 0
