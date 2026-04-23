"""Vonage response formatters."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.sandbox.models import SandboxCall, SandboxMessage, SandboxPhoneNumber
    from app.sandbox.seeds.available_numbers import AvailableNumber


def _isoformat(ts: datetime | None) -> str:
    return (ts or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_message_uuid() -> str:
    return str(uuid.uuid4())


def new_call_uuid() -> str:
    return str(uuid.uuid4())


def format_message_send_response(message: SandboxMessage) -> dict[str, Any]:
    return {"message_uuid": message.external_id or new_message_uuid()}


def format_inbound_message_webhook(
    message: SandboxMessage, channel: str = "sms"
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message_uuid": message.external_id or new_message_uuid(),
        "to": {"type": channel, "number": message.metadata_json.get("to", "")},
        "from": {"type": channel, "number": message.metadata_json.get("from", message.sender)},
        "timestamp": _isoformat(message.created_at),
        "channel": channel,
        "message_type": message.metadata_json.get("message_type", "text"),
        "text": message.content or "",
    }
    media = message.metadata_json.get("media_urls") or []
    mt = payload["message_type"]
    if mt in {"image", "video", "audio", "file"} and media:
        payload[mt] = {"url": media[0]}
    return payload


def format_message_status_webhook(message: SandboxMessage, status: str) -> dict[str, Any]:
    return {
        "message_uuid": message.external_id,
        "to": message.metadata_json.get("to", ""),
        "from": message.metadata_json.get("from", message.sender),
        "timestamp": _isoformat(message.created_at),
        "status": status,
        "usage": {"currency": "EUR", "price": "0.0000"},
    }


def format_call(call: SandboxCall) -> dict[str, Any]:
    return {
        "uuid": call.external_id,
        "conversation_uuid": call.metadata_json.get("conversation_uuid", str(uuid.uuid4())),
        "direction": call.direction,
        "status": call.status,
        "from": {"type": "phone", "number": call.from_number},
        "to": [{"type": "phone", "number": call.to_number}],
        "start_time": _isoformat(call.answered_at) if call.answered_at else None,
        "end_time": _isoformat(call.ended_at) if call.ended_at else None,
        "duration": str(call.duration_seconds) if call.duration_seconds else None,
        "rate": "0.00390",
        "price": "0.000",
        "network": "GENERIC",
        "_links": {
            "self": {"href": f"/v1/calls/{call.external_id}"},
        },
    }


def format_call_list(calls: list[SandboxCall]) -> dict[str, Any]:
    return {
        "page_size": 100,
        "count": len(calls),
        "record_index": 0,
        "_embedded": {"calls": [format_call(c) for c in calls]},
        "_links": {"self": {"href": "/v1/calls"}},
    }


def format_owned_numbers(nums: list[SandboxPhoneNumber]) -> dict[str, Any]:
    return {
        "count": len(nums),
        "numbers": [
            {
                "country": n.iso_country,
                "msisdn": n.e164.lstrip("+"),
                "moHttpUrl": n.sms_url,
                "type": "mobile-lvn" if n.number_type == "mobile" else "landline",
                "features": [
                    f
                    for f, enabled in (
                        ("VOICE", n.capabilities.get("voice", False)),
                        ("SMS", n.capabilities.get("sms", False)),
                        ("MMS", n.capabilities.get("mms", False)),
                    )
                    if enabled
                ],
                "voiceCallbackType": "app" if n.voice_url else None,
                "voiceCallbackValue": n.voice_url,
                "messagesCallbackType": "app" if n.sms_url else None,
                "messagesCallbackValue": n.sms_url,
            }
            for n in nums
        ],
    }


def format_available_numbers(numbers: list[AvailableNumber]) -> dict[str, Any]:
    return {
        "count": len(numbers),
        "numbers": [
            {
                "country": n.iso_country,
                "msisdn": n.e164.lstrip("+"),
                "type": {
                    "local": "landline",
                    "mobile": "mobile-lvn",
                    "tollfree": "landline-toll-free",
                }.get(n.number_type, "landline"),
                "cost": "1.25",
                "features": [
                    f
                    for f, enabled in (
                        ("VOICE", n.capabilities.get("voice", False)),
                        ("SMS", n.capabilities.get("sms", False)),
                        ("MMS", n.capabilities.get("mms", False)),
                    )
                    if enabled
                ],
            }
            for n in numbers
        ],
    }
