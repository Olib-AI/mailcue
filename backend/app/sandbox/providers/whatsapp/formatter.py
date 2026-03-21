"""Format sandbox data into WhatsApp Business Cloud API response shapes."""

from __future__ import annotations

import calendar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.sandbox.models import SandboxMessage, SandboxProvider


def format_message_response(
    message: SandboxMessage,
    phone_number_id: str,
) -> dict[str, object]:
    """Return a WhatsApp Cloud API send-message response.

    Shape::

        {
          "messaging_product": "whatsapp",
          "contacts": [{"input": "<to>", "wa_id": "<to>"}],
          "messages": [{"id": "wamid..."}]
        }
    """
    recipient = message.metadata_json.get("to", message.sender)
    return {
        "messaging_product": "whatsapp",
        "contacts": [{"input": str(recipient), "wa_id": str(recipient)}],
        "messages": [{"id": message.external_id or message.id}],
    }


def format_webhook_payload(
    message: SandboxMessage,
    phone_number_id: str,
    provider: SandboxProvider,
) -> dict[str, object]:
    """Return a WhatsApp Cloud API webhook payload for an inbound message.

    Shape follows the real webhook ``object: whatsapp_business_account`` format.
    """
    timestamp = str(int(calendar.timegm(message.created_at.timetuple())))
    wa_id = message.metadata_json.get("from", message.sender)

    wa_message: dict[str, object] = {
        "from": str(wa_id),
        "id": message.external_id or message.id,
        "timestamp": timestamp,
        "type": message.content_type or "text",
    }

    if message.content_type == "text":
        wa_message["text"] = {"body": message.content or ""}
    elif message.content_type in ("image", "document", "audio", "video"):
        wa_message[message.content_type] = {
            "id": f"media_{message.id}",
            "mime_type": message.metadata_json.get("mime_type", "application/octet-stream"),
        }
        if message.content:
            wa_message[message.content_type] = {  # type: ignore[assignment]
                **wa_message[message.content_type],  # type: ignore[arg-type]
                "caption": message.content,
            }

    display_phone = provider.credentials.get("display_phone_number", phone_number_id)

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": provider.id,
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": str(display_phone),
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [
                                {
                                    "profile": {"name": message.sender},
                                    "wa_id": str(wa_id),
                                }
                            ],
                            "messages": [wa_message],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
