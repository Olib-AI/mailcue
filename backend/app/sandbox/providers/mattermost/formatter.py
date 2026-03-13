"""Format sandbox data into Mattermost API v4 response shapes."""

from __future__ import annotations

import calendar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.sandbox.models import SandboxConversation, SandboxMessage, SandboxProvider


def format_post(message: SandboxMessage, channel_id: str) -> dict[str, Any]:
    """Return a Mattermost Post object from a stored sandbox message."""
    create_at = int(calendar.timegm(message.created_at.timetuple()) * 1000)
    return {
        "id": message.external_id or message.id,
        "channel_id": channel_id,
        "message": message.content or "",
        "user_id": message.sender,
        "create_at": create_at,
        "update_at": create_at,
        "delete_at": 0,
        "type": "",
    }


def format_channel(conversation: SandboxConversation) -> dict[str, Any]:
    """Return a Mattermost Channel object from a sandbox conversation."""
    team_id = f"t{abs(hash(conversation.provider_id)) % (10**10):010d}"
    return {
        "id": conversation.external_id,
        "name": (conversation.name or conversation.external_id).lower().replace(" ", "-"),
        "display_name": conversation.name or conversation.external_id,
        "type": "O",
        "team_id": team_id,
    }


def format_user(provider: SandboxProvider) -> dict[str, Any]:
    """Return a Mattermost User object for the bot."""
    user_id = f"u{abs(hash(provider.id)) % (10**25):025d}"
    return {
        "id": user_id,
        "username": provider.name,
        "email": f"{provider.name}@mailcue.sandbox",
        "first_name": "MailCue",
        "last_name": "Bot",
    }
