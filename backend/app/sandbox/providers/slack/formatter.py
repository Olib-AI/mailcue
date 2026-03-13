"""Format sandbox data into Slack Web API response shapes."""

from __future__ import annotations

import calendar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.sandbox.models import SandboxConversation, SandboxMessage, SandboxProvider


def format_message(message: SandboxMessage, channel_id: str) -> dict[str, Any]:
    """Return a Slack message object from a stored sandbox message."""
    ts_epoch = calendar.timegm(message.created_at.timetuple())
    ts_micro = message.created_at.microsecond if hasattr(message.created_at, "microsecond") else 0
    ts = f"{ts_epoch}.{ts_micro:06d}"

    result: dict[str, Any] = {
        "type": "message",
        "channel": channel_id,
        "user": message.sender,
        "text": message.content or "",
        "ts": ts,
    }

    if message.metadata_json.get("edited"):
        result["edited"] = {
            "user": message.sender,
            "ts": ts,
        }

    return result


def format_channel(conversation: SandboxConversation) -> dict[str, Any]:
    """Return a Slack channel object from a sandbox conversation."""
    return {
        "id": conversation.external_id,
        "name": conversation.name or conversation.external_id,
        "is_channel": True,
        "is_member": True,
        "num_members": 1,
    }


def format_user(provider: SandboxProvider) -> dict[str, Any]:
    """Return a Slack user object for the bot."""
    user_id = f"U{abs(hash(provider.id)) % (10**10):010d}"
    return {
        "id": user_id,
        "name": provider.name,
        "real_name": provider.name,
        "is_bot": True,
    }


def format_event_payload(
    message: SandboxMessage,
    provider: SandboxProvider,
) -> dict[str, Any]:
    """Return a Slack Events API envelope."""
    ts_epoch = calendar.timegm(message.created_at.timetuple())
    ts_micro = message.created_at.microsecond if hasattr(message.created_at, "microsecond") else 0
    event_ts = f"{ts_epoch}.{ts_micro:06d}"
    team_id = f"T{abs(hash(provider.id)) % (10**10):010d}"

    return {
        "token": "sandbox_verification_token",
        "team_id": team_id,
        "event": {
            "type": "message",
            "channel": message.conversation_id or "",
            "user": message.sender,
            "text": message.content or "",
            "ts": event_ts,
        },
        "type": "event_callback",
        "event_id": f"Ev{abs(hash(message.id)) % (10**10):010d}",
        "event_time": ts_epoch,
    }
