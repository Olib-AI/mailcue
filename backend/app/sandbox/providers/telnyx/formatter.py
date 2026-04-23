"""Telnyx v2 JSON:API response formatters."""

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
        SandboxNumberOrder,
        SandboxPhoneNumber,
        SandboxPortRequest,
    )
    from app.sandbox.seeds.available_numbers import AvailableNumber


def _isoformat(ts: datetime | None) -> str:
    return (ts or datetime.now(UTC)).isoformat().replace("+00:00", "Z")


def new_message_id() -> str:
    return str(uuid.uuid4())


def new_call_id() -> str:
    return str(uuid.uuid4())


def new_call_control_id() -> str:
    return "v3:" + uuid.uuid4().hex


def new_order_id() -> str:
    return str(uuid.uuid4())


def new_port_id() -> str:
    return str(uuid.uuid4())


def new_brand_id() -> str:
    return str(uuid.uuid4())


def new_campaign_id() -> str:
    return str(uuid.uuid4())


def format_message(message: SandboxMessage) -> dict[str, Any]:
    to_raw = message.metadata_json.get("to")
    to_list = to_raw if isinstance(to_raw, list) else ([to_raw] if to_raw else [])
    media = message.metadata_json.get("media_urls", []) or []
    return {
        "data": {
            "id": message.external_id,
            "record_type": "message",
            "direction": "outbound" if message.direction == "outbound" else "inbound",
            "type": "MMS" if media else "SMS",
            "from": {
                "phone_number": message.metadata_json.get("from", message.sender),
                "carrier": "T-Mobile USA",
                "line_type": "long_code",
            },
            "to": [
                {
                    "phone_number": t,
                    "status": "queued",
                    "carrier": "T-Mobile USA",
                    "line_type": "long_code",
                }
                for t in to_list
            ],
            "text": message.content or "",
            "subject": None,
            "media": [{"url": u} for u in media],
            "webhook_url": message.metadata_json.get("webhook_url"),
            "webhook_failover_url": None,
            "encoding": "GSM-7",
            "parts": 1,
            "tags": [],
            "cost": {"amount": "0.0040", "currency": "USD"},
            "received_at": _isoformat(message.created_at),
            "sent_at": None,
            "completed_at": None,
            "valid_until": None,
            "errors": [],
            "messaging_profile_id": message.metadata_json.get("messaging_profile_id"),
        }
    }


def format_call(call: SandboxCall) -> dict[str, Any]:
    return {
        "data": {
            "record_type": "call",
            "call_session_id": call.external_id,
            "call_leg_id": call.external_id,
            "call_control_id": call.metadata_json.get("call_control_id", call.external_id),
            "from": call.from_number,
            "to": call.to_number,
            "direction": call.direction,
            "state": call.status,
            "answered_at": _isoformat(call.answered_at) if call.answered_at else None,
            "ended_at": _isoformat(call.ended_at) if call.ended_at else None,
            "duration": call.duration_seconds,
            "client_state": call.metadata_json.get("client_state"),
        }
    }


def format_available_numbers(numbers: list[AvailableNumber]) -> dict[str, Any]:
    return {
        "data": [
            {
                "record_type": "available_phone_number",
                "phone_number": n.e164,
                "vanity_format": "",
                "best_effort": False,
                "quickship": True,
                "reservable": True,
                "region_information": [
                    {"region_type": "country_code", "region_name": n.iso_country},
                    {"region_type": "city", "region_name": n.locality},
                    {"region_type": "state", "region_name": n.region},
                ],
                "cost_information": {
                    "upfront_cost": "1.00",
                    "monthly_cost": "1.00",
                    "currency": "USD",
                },
                "features": [
                    {"name": f}
                    for f, enabled in (
                        ("sms", n.capabilities.get("sms", False)),
                        ("mms", n.capabilities.get("mms", False)),
                        ("voice", n.capabilities.get("voice", False)),
                        ("fax", n.capabilities.get("fax", False)),
                    )
                    if enabled
                ],
            }
            for n in numbers
        ],
        "meta": {"total_results": len(numbers), "best_effort_results": 0},
    }


def format_owned_number(pn: SandboxPhoneNumber) -> dict[str, Any]:
    return {
        "record_type": "phone_number",
        "id": pn.external_id,
        "phone_number": pn.e164,
        "status": "active" if not pn.released else "deleted",
        "tags": [],
        "external_pin": None,
        "connection_id": pn.metadata_json.get("connection_id"),
        "connection_name": pn.metadata_json.get("connection_name"),
        "customer_reference": None,
        "messaging_profile_id": pn.metadata_json.get("messaging_profile_id"),
        "messaging_profile_name": pn.metadata_json.get("messaging_profile_name"),
        "billing_group_id": None,
        "emergency_enabled": False,
        "emergency_address_id": None,
        "call_forwarding_enabled": False,
        "cnam_listing_enabled": False,
        "caller_id_name_enabled": False,
        "call_recording_enabled": False,
        "t38_fax_gateway_enabled": False,
        "country_iso": pn.iso_country,
        "phone_number_type": pn.number_type,
        "purchased_at": _isoformat(pn.created_at),
        "created_at": _isoformat(pn.created_at),
        "updated_at": _isoformat(pn.created_at),
    }


def format_owned_numbers(nums: list[SandboxPhoneNumber]) -> dict[str, Any]:
    return {
        "data": [format_owned_number(n) for n in nums],
        "meta": {
            "total_pages": 1,
            "total_results": len(nums),
            "page_number": 1,
            "page_size": 20,
        },
    }


def format_number_order(order: SandboxNumberOrder) -> dict[str, Any]:
    return {
        "data": {
            "record_type": "number_order",
            "id": order.external_id,
            "status": order.status,
            "phone_numbers_count": len(order.numbers),
            "phone_numbers": [{"phone_number": n, "status": "success"} for n in order.numbers],
            "customer_reference": order.raw_request.get("customer_reference"),
            "requirements_met": True,
            "sub_number_orders_ids": [],
            "created_at": _isoformat(order.created_at),
            "updated_at": _isoformat(order.created_at),
        }
    }


def format_port_order(port: SandboxPortRequest) -> dict[str, Any]:
    return {
        "data": {
            "record_type": "porting_order",
            "id": port.external_id,
            "status": {"value": port.status, "details": []},
            "phone_numbers": [{"phone_number": n} for n in port.numbers],
            "customer_reference": port.raw_request.get("customer_reference"),
            "desired_foc_date": port.foc_date.isoformat() if port.foc_date else None,
            "user_feedback": None,
            "webhook_url": port.raw_request.get("webhook_url"),
            "created_at": _isoformat(port.created_at),
            "updated_at": _isoformat(port.created_at),
        }
    }


def format_brand(brand: SandboxBrand) -> dict[str, Any]:
    raw = brand.raw_request
    return {
        "brandId": brand.external_id,
        "entityType": raw.get("entityType", "PRIVATE_PROFIT"),
        "firstName": raw.get("firstName"),
        "lastName": raw.get("lastName"),
        "displayName": raw.get("displayName", raw.get("brand_name", "")),
        "companyName": raw.get("companyName", raw.get("displayName", "")),
        "ein": raw.get("ein"),
        "email": raw.get("email"),
        "phone": raw.get("phone"),
        "street": raw.get("street"),
        "city": raw.get("city"),
        "state": raw.get("state"),
        "postalCode": raw.get("postalCode"),
        "country": raw.get("country", "US"),
        "stockSymbol": raw.get("stockSymbol"),
        "stockExchange": raw.get("stockExchange"),
        "brandRelationship": raw.get("brandRelationship", "BASIC_ACCOUNT"),
        "vertical": raw.get("vertical", "TECHNOLOGY"),
        "status": brand.status,
        "identityStatus": "VERIFIED" if brand.status == "APPROVED" else "UNVERIFIED",
        "createdAt": _isoformat(brand.created_at),
        "updatedAt": _isoformat(brand.created_at),
    }


def format_campaign(campaign: SandboxCampaign) -> dict[str, Any]:
    raw = campaign.raw_request
    return {
        "campaignId": campaign.external_id,
        "tcrBrandId": raw.get("brandId"),
        "usecase": campaign.use_case,
        "description": campaign.description,
        "sample1": campaign.sample_messages[0] if campaign.sample_messages else "",
        "sample2": campaign.sample_messages[1] if len(campaign.sample_messages) > 1 else "",
        "status": campaign.status,
        "embeddedLink": raw.get("embeddedLink", False),
        "embeddedPhone": raw.get("embeddedPhone", False),
        "subscriberOptin": raw.get("subscriberOptin", True),
        "subscriberOptout": raw.get("subscriberOptout", True),
        "subscriberHelp": raw.get("subscriberHelp", True),
        "ageGated": raw.get("ageGated", False),
        "numberPool": raw.get("numberPool", False),
        "directLending": raw.get("directLending", False),
        "affiliateMarketing": raw.get("affiliateMarketing", False),
        "createdAt": _isoformat(campaign.created_at),
    }
