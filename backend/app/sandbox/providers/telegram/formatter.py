"""Format sandbox data into Telegram Bot API response shapes."""

from __future__ import annotations

import calendar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.sandbox.models import SandboxMessage, SandboxProvider


def format_bot_info(provider: SandboxProvider) -> dict[str, object]:
    """Return a Telegram User object representing the bot."""
    return {
        "id": abs(hash(provider.id)) % (10**9),
        "is_bot": True,
        "first_name": provider.name,
        "username": f"{provider.name}_bot",
    }


def format_message(
    message: SandboxMessage,
    chat_id: int,
    bot_info: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return a Telegram Message object from a stored sandbox message."""
    msg_id = abs(hash(message.id)) % (10**9)
    date_unix = int(calendar.timegm(message.created_at.timetuple()))

    result: dict[str, object] = {
        "message_id": msg_id,
        "chat": {
            "id": chat_id,
            "type": "private",
        },
        "date": date_unix,
    }

    if bot_info is not None:
        result["from"] = bot_info

    if message.content is not None:
        result["text"] = message.content

    if message.metadata_json.get("edit_date"):
        result["edit_date"] = message.metadata_json["edit_date"]

    return result


def format_webhook_update(
    message: SandboxMessage,
    update_id: int,
    chat_id: int,
) -> dict[str, object]:
    """Return a Telegram Update object wrapping an inbound message."""
    msg = format_message(message, chat_id)
    # Inbound messages come from a user, not the bot
    msg["from"] = {
        "id": chat_id,
        "is_bot": False,
        "first_name": message.sender,
        "username": message.sender,
    }
    return {
        "update_id": update_id,
        "message": msg,
    }
