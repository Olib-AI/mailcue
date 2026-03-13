"""Pydantic schemas mirroring Slack Web API data structures."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SlackMessage(BaseModel):
    """Slack message object."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    type: str = "message"
    channel: str
    user: str
    text: str
    ts: str
    edited: dict[str, Any] | None = None


class SlackChannel(BaseModel):
    """Slack channel object."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: str
    name: str
    is_channel: bool = True
    is_member: bool = True
    num_members: int = 1


class SlackUser(BaseModel):
    """Slack user object."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: str
    name: str
    real_name: str
    is_bot: bool = True


class SlackResponse(BaseModel):
    """Standard Slack Web API response envelope."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    ok: bool = True
    error: str | None = None


class ChatPostMessageRequest(BaseModel):
    """Request body for chat.postMessage."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    channel: str
    text: str
    thread_ts: str | None = None


class ChatUpdateRequest(BaseModel):
    """Request body for chat.update."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    channel: str
    ts: str
    text: str


class ChatDeleteRequest(BaseModel):
    """Request body for chat.delete."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    channel: str
    ts: str
