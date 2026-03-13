"""Format sandbox data into Twilio REST API response shapes."""

from __future__ import annotations

import uuid
from email.utils import formatdate
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.sandbox.models import SandboxMessage


def generate_sid(prefix: str = "SM") -> str:
    """Generate a Twilio-style SID: prefix + 32 hex characters."""
    return f"{prefix}{uuid.uuid4().hex}"


def format_message(message: SandboxMessage, account_sid: str) -> dict[str, Any]:
    """Return a Twilio Message resource from a stored sandbox message."""
    sid = message.external_id or generate_sid()
    date_rfc2822 = formatdate(timeval=message.created_at.timestamp(), localtime=False, usegmt=True)

    # Determine from/to from metadata or defaults
    from_number = message.metadata_json.get("from", message.sender)
    to_number = message.metadata_json.get("to", "")
    direction_str = "outbound-api" if message.direction == "outbound" else "inbound"

    uri = f"/2010-04-01/Accounts/{account_sid}/Messages/{sid}.json"

    return {
        "sid": sid,
        "account_sid": account_sid,
        "from": from_number,
        "to": to_number,
        "body": message.content or "",
        "status": "queued" if message.direction == "outbound" else "received",
        "direction": direction_str,
        "date_created": date_rfc2822,
        "date_updated": date_rfc2822,
        "date_sent": None,
        "num_segments": "1",
        "price": None,
        "price_unit": "USD",
        "uri": uri,
    }


def format_message_list(messages: list[SandboxMessage], account_sid: str) -> dict[str, Any]:
    """Return a Twilio message list envelope."""
    formatted = [format_message(m, account_sid) for m in messages]
    uri = f"/2010-04-01/Accounts/{account_sid}/Messages.json"
    return {
        "messages": formatted,
        "end": len(formatted) - 1 if formatted else 0,
        "first_page_uri": f"{uri}?Page=0&PageSize=50",
        "next_page_uri": None,
        "page": 0,
        "page_size": 50,
        "start": 0,
        "uri": uri,
    }
