"""Pydantic schemas mirroring Mattermost API v4 data structures."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MattermostPost(BaseModel):
    """Mattermost Post object."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: str
    channel_id: str
    message: str
    user_id: str
    create_at: int
    update_at: int
    delete_at: int = 0
    type: str = ""


class MattermostChannel(BaseModel):
    """Mattermost Channel object."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: str
    name: str
    display_name: str
    type: str = "O"
    team_id: str


class MattermostUser(BaseModel):
    """Mattermost User object."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: str
    username: str
    email: str
    first_name: str = "MailCue"
    last_name: str = "Bot"


class CreatePostRequest(BaseModel):
    """Request body for creating a post."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    channel_id: str
    message: str
    root_id: str | None = None


class PostListResponse(BaseModel):
    """Mattermost post list response."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    order: list[str]
    posts: dict[str, Any]
