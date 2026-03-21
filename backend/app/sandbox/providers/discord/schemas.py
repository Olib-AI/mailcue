"""Pydantic schemas mirroring Discord Bot API data structures."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CreateMessageRequest(BaseModel):
    """Request body for creating a message in a channel."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    content: str | None = None
    embeds: list[dict[str, Any]] | None = None
    tts: bool = False


class EditMessageRequest(BaseModel):
    """Request body for editing an existing message."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    content: str | None = None
    embeds: list[dict[str, Any]] | None = None


class CreateChannelRequest(BaseModel):
    """Request body for creating a guild channel."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    name: str
    type: int = 0  # 0 = GUILD_TEXT
