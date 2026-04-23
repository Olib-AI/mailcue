"""Plivo response formatters (form-encoded input, JSON output)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.sandbox.models import (
        SandboxBrand,
        SandboxCall,
        SandboxCampaign,
        SandboxMessage,
        SandboxPhoneNumber,
        SandboxPortRequest,
    )
    from app.sandbox.seeds.available_numbers import AvailableNumber


def _isoformat(ts: datetime | None) -> str:
    return (ts or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M:%S%z") or ""


def new_message_uuid() -> str:
    return str(uuid.uuid4())


def new_call_uuid() -> str:
    return str(uuid.uuid4())


def new_brand_id() -> str:
    return "BR" + uuid.uuid4().hex[:10].upper()


def new_campaign_id() -> str:
    return "CP" + uuid.uuid4().hex[:10].upper()


def new_port_id() -> str:
    return uuid.uuid4().hex[:24]


def format_send_message_response(message: SandboxMessage, auth_id: str) -> dict[str, Any]:
    return {
        "api_id": str(uuid.uuid4()),
        "message": "message(s) queued",
        "message_uuid": [message.external_id or new_message_uuid()],
    }


def format_message(message: SandboxMessage, auth_id: str) -> dict[str, Any]:
    media = message.metadata_json.get("media_urls", []) or []
    to_list = message.metadata_json.get("to") or []
    to = (
        to_list[0]
        if isinstance(to_list, list) and to_list
        else message.metadata_json.get("to", "")
    )
    return {
        "api_id": str(uuid.uuid4()),
        "message_uuid": message.external_id,
        "from_number": message.metadata_json.get("from", message.sender),
        "to_number": to,
        "message_state": "queued",
        "message_type": "mms" if media else "sms",
        "message_direction": "outbound" if message.direction == "outbound" else "inbound",
        "message_time": _isoformat(message.created_at),
        "total_amount": "0.00000",
        "total_rate": "0.00350",
        "units": 1,
        "resource_uri": f"/v1/Account/{auth_id}/Message/{message.external_id}/",
        "error_code": None,
        "media_urls": media,
        "powerpack_uuid": None,
        "requester_ip": "127.0.0.1",
        "is_domestic": True,
        "replaced_sender": None,
    }


def format_message_list(messages: list[SandboxMessage], auth_id: str) -> dict[str, Any]:
    return {
        "api_id": str(uuid.uuid4()),
        "meta": {
            "limit": 20,
            "next": None,
            "offset": 0,
            "previous": None,
            "total_count": len(messages),
        },
        "objects": [format_message(m, auth_id) for m in messages],
    }


def format_call(call: SandboxCall, auth_id: str) -> dict[str, Any]:
    return {
        "api_id": str(uuid.uuid4()),
        "request_uuid": call.external_id,
        "message": "call fired",
        "call_uuid": call.external_id,
        "from_number": call.from_number,
        "to_number": call.to_number,
        "call_status": call.status,
        "call_duration": call.duration_seconds,
        "answer_time": _isoformat(call.answered_at) if call.answered_at else None,
        "end_time": _isoformat(call.ended_at) if call.ended_at else None,
        "resource_uri": f"/v1/Account/{auth_id}/Call/{call.external_id}/",
    }


def format_call_list(calls: list[SandboxCall], auth_id: str) -> dict[str, Any]:
    return {
        "api_id": str(uuid.uuid4()),
        "meta": {
            "limit": 20,
            "next": None,
            "offset": 0,
            "previous": None,
            "total_count": len(calls),
        },
        "objects": [format_call(c, auth_id) for c in calls],
    }


def format_owned_number(pn: SandboxPhoneNumber, auth_id: str) -> dict[str, Any]:
    return {
        "api_id": str(uuid.uuid4()),
        "number": pn.e164.lstrip("+"),
        "country": pn.iso_country,
        "type": {
            "local": "local",
            "mobile": "mobile",
            "tollfree": "tollfree",
        }.get(pn.number_type, "local"),
        "monthly_rental_rate": "0.8000",
        "application": None,
        "voice_enabled": bool(pn.capabilities.get("voice")),
        "sms_enabled": bool(pn.capabilities.get("sms")),
        "mms_enabled": bool(pn.capabilities.get("mms")),
        "voice_rate": "0.00650",
        "sms_rate": "0.00350",
        "added_on": _isoformat(pn.created_at),
        "resource_uri": f"/v1/Account/{auth_id}/Number/{pn.e164.lstrip('+')}/",
        "region": pn.region,
    }


def format_owned_number_list(nums: list[SandboxPhoneNumber], auth_id: str) -> dict[str, Any]:
    return {
        "api_id": str(uuid.uuid4()),
        "meta": {
            "limit": 20,
            "next": None,
            "offset": 0,
            "previous": None,
            "total_count": len(nums),
        },
        "objects": [format_owned_number(n, auth_id) for n in nums],
    }


def format_available_number_list(numbers: list[AvailableNumber]) -> dict[str, Any]:
    return {
        "api_id": str(uuid.uuid4()),
        "meta": {
            "limit": 20,
            "next": None,
            "offset": 0,
            "previous": None,
            "total_count": len(numbers),
        },
        "objects": [
            {
                "number": n.e164.lstrip("+"),
                "country": n.iso_country,
                "type": n.number_type,
                "region": n.region,
                "city": n.locality,
                "voice_enabled": bool(n.capabilities.get("voice")),
                "sms_enabled": bool(n.capabilities.get("sms")),
                "mms_enabled": bool(n.capabilities.get("mms")),
                "monthly_rental_rate": "0.8000",
                "setup_rate": "0.0000",
            }
            for n in numbers
        ],
    }


def format_brand(brand: SandboxBrand) -> dict[str, Any]:
    raw = brand.raw_request
    return {
        "api_id": str(uuid.uuid4()),
        "brand_id": brand.external_id,
        "status": brand.status,
        "company_name": raw.get("company_name", raw.get("brand_name", "")),
        "ein": raw.get("ein"),
        "vertical": raw.get("vertical", "TECHNOLOGY"),
        "brand_score": 75,
        "identity_status": "VERIFIED" if brand.status == "APPROVED" else "PENDING",
        "created_at": (brand.created_at.isoformat() if brand.created_at else ""),
    }


def format_campaign(campaign: SandboxCampaign) -> dict[str, Any]:
    raw = campaign.raw_request
    return {
        "api_id": str(uuid.uuid4()),
        "campaign_id": campaign.external_id,
        "status": campaign.status,
        "brand_id": raw.get("brand_id"),
        "usecase": campaign.use_case,
        "description": campaign.description,
        "sample_messages": campaign.sample_messages,
        "has_embedded_links": bool(raw.get("has_embedded_links", False)),
        "has_embedded_phone": bool(raw.get("has_embedded_phone", False)),
        "created_at": (campaign.created_at.isoformat() if campaign.created_at else ""),
    }


def format_port_request(port: SandboxPortRequest) -> dict[str, Any]:
    return {
        "api_id": str(uuid.uuid4()),
        "port_id": port.external_id,
        "status": port.status,
        "phone_numbers": port.numbers,
        "loa_info": port.loa_info,
        "foc_date": (port.foc_date.isoformat() if port.foc_date else None),
        "created_at": (port.created_at.isoformat() if port.created_at else ""),
        "message": "Port request received",
    }
