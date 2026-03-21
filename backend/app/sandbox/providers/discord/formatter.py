"""Format sandbox data into Discord Bot API response shapes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.sandbox.models import SandboxConversation, SandboxMessage


def format_message(
    message: SandboxMessage,
    channel_id: str,
    author: dict[str, Any],
) -> dict[str, Any]:
    """Return a Discord Message object.

    Shape follows the Discord API message structure documented at
    https://discord.com/developers/docs/resources/message#message-object
    """
    timestamp = (
        message.created_at.isoformat() + "Z" if message.created_at else "1970-01-01T00:00:00Z"
    )
    embeds: list[dict[str, Any]] = message.metadata_json.get("embeds", [])
    tts: bool = message.metadata_json.get("tts", False)

    return {
        "id": message.external_id or message.id,
        "type": 0,
        "content": message.content or "",
        "channel_id": channel_id,
        "author": author,
        "timestamp": timestamp,
        "edited_timestamp": message.metadata_json.get("edited_timestamp"),
        "tts": tts,
        "mention_everyone": False,
        "mentions": [],
        "mention_roles": [],
        "attachments": [],
        "embeds": embeds,
        "pinned": False,
    }


def format_channel(
    conversation: SandboxConversation,
    guild_id: str,
) -> dict[str, Any]:
    """Return a Discord Channel object.

    Shape follows the Discord API channel structure documented at
    https://discord.com/developers/docs/resources/channel#channel-object
    """
    channel_type = conversation.metadata_json.get("channel_type", 0)
    return {
        "id": conversation.external_id,
        "type": channel_type,
        "guild_id": guild_id,
        "name": conversation.name or "general",
        "position": 0,
        "permission_overwrites": [],
        "topic": None,
        "nsfw": False,
        "last_message_id": None,
        "rate_limit_per_user": 0,
    }


def format_webhook_payload(
    message: SandboxMessage,
    channel_id: str,
    guild_id: str,
    author: dict[str, Any],
) -> dict[str, Any]:
    """Return a Discord gateway MESSAGE_CREATE event payload.

    Shape follows the Discord gateway dispatch event format.
    """
    msg = format_message(message, channel_id, author)
    msg["guild_id"] = guild_id
    return {
        "t": "MESSAGE_CREATE",
        "s": None,
        "op": 0,
        "d": msg,
    }
