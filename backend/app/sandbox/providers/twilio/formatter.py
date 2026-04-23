"""Format sandbox data into Twilio REST API response shapes."""

from __future__ import annotations

import uuid
from datetime import datetime
from email.utils import formatdate
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


def _rfc2822(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return formatdate(timeval=ts.timestamp(), localtime=False, usegmt=True)


def generate_sid(prefix: str = "SM") -> str:
    """Generate a Twilio-style SID: prefix + 32 hex characters."""
    return f"{prefix}{uuid.uuid4().hex}"


def format_message(message: SandboxMessage, account_sid: str) -> dict[str, Any]:
    """Return a Twilio Message resource from a stored sandbox message."""
    sid = message.external_id or generate_sid()
    date_rfc2822 = _rfc2822(message.created_at)

    from_number = message.metadata_json.get("from", message.sender)
    to_number = message.metadata_json.get("to", "")
    direction_str = "outbound-api" if message.direction == "outbound" else "inbound"

    uri = f"/2010-04-01/Accounts/{account_sid}/Messages/{sid}.json"
    media_urls: list[str] = message.metadata_json.get("media_urls", []) or []
    num_media = str(len(media_urls))

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
        "num_media": num_media,
        "price": None,
        "price_unit": "USD",
        "uri": uri,
        "subresource_uris": {
            "media": f"/2010-04-01/Accounts/{account_sid}/Messages/{sid}/Media.json"
        },
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


def format_call(call: SandboxCall, account_sid: str) -> dict[str, Any]:
    uri = f"/2010-04-01/Accounts/{account_sid}/Calls/{call.external_id}.json"
    return {
        "sid": call.external_id,
        "account_sid": account_sid,
        "to": call.to_number,
        "to_formatted": call.to_number,
        "from": call.from_number,
        "from_formatted": call.from_number,
        "phone_number_sid": None,
        "status": call.status,
        "start_time": _rfc2822(call.answered_at),
        "end_time": _rfc2822(call.ended_at),
        "duration": str(call.duration_seconds) if call.duration_seconds else None,
        "price": call.price,
        "price_unit": call.price_unit,
        "direction": "outbound-api" if call.direction == "outbound" else "inbound",
        "answered_by": None,
        "api_version": "2010-04-01",
        "forwarded_from": None,
        "group_sid": None,
        "caller_name": None,
        "uri": uri,
        "date_created": _rfc2822(call.created_at),
        "date_updated": _rfc2822(call.created_at),
        "parent_call_sid": None,
        "subresource_uris": {
            "recordings": f"/2010-04-01/Accounts/{account_sid}/Calls/{call.external_id}/Recordings.json",
            "notifications": f"/2010-04-01/Accounts/{account_sid}/Calls/{call.external_id}/Notifications.json",
        },
    }


def format_call_list(calls: list[SandboxCall], account_sid: str) -> dict[str, Any]:
    formatted = [format_call(c, account_sid) for c in calls]
    uri = f"/2010-04-01/Accounts/{account_sid}/Calls.json"
    return {
        "calls": formatted,
        "end": len(formatted) - 1 if formatted else 0,
        "first_page_uri": f"{uri}?Page=0&PageSize=50",
        "next_page_uri": None,
        "page": 0,
        "page_size": 50,
        "start": 0,
        "uri": uri,
    }


def format_available_number(num: AvailableNumber, account_sid: str) -> dict[str, Any]:
    return {
        "friendly_name": num.e164,
        "phone_number": num.e164,
        "lata": "0000",
        "locality": num.locality,
        "rate_center": num.locality,
        "latitude": None,
        "longitude": None,
        "region": num.region,
        "postal_code": None,
        "iso_country": num.iso_country,
        "address_requirements": "none",
        "beta": False,
        "capabilities": {
            "voice": bool(num.capabilities.get("voice")),
            "SMS": bool(num.capabilities.get("sms")),
            "MMS": bool(num.capabilities.get("mms")),
            "fax": bool(num.capabilities.get("fax")),
        },
    }


def format_available_number_list(
    numbers: list[AvailableNumber], account_sid: str, country: str, number_type: str
) -> dict[str, Any]:
    uri = f"/2010-04-01/Accounts/{account_sid}/AvailablePhoneNumbers/{country}/{number_type}.json"
    return {
        "uri": uri,
        "available_phone_numbers": [format_available_number(n, account_sid) for n in numbers],
    }


def format_incoming_number(pn: SandboxPhoneNumber, account_sid: str) -> dict[str, Any]:
    uri = f"/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers/{pn.external_id}.json"
    return {
        "sid": pn.external_id,
        "account_sid": account_sid,
        "phone_number": pn.e164,
        "friendly_name": pn.metadata_json.get("friendly_name", pn.e164),
        "date_created": _rfc2822(pn.created_at),
        "date_updated": _rfc2822(pn.created_at),
        "voice_url": pn.voice_url,
        "voice_method": pn.voice_method,
        "sms_url": pn.sms_url,
        "sms_method": pn.sms_method,
        "status_callback": pn.status_callback,
        "capabilities": {
            "voice": bool(pn.capabilities.get("voice")),
            "SMS": bool(pn.capabilities.get("sms")),
            "MMS": bool(pn.capabilities.get("mms")),
            "fax": bool(pn.capabilities.get("fax")),
        },
        "origin": "twilio",
        "beta": False,
        "uri": uri,
        "status": "in-use" if not pn.released else "released",
        "address_requirements": "none",
        "api_version": "2010-04-01",
    }


def format_incoming_number_list(
    numbers: list[SandboxPhoneNumber], account_sid: str
) -> dict[str, Any]:
    uri = f"/2010-04-01/Accounts/{account_sid}/IncomingPhoneNumbers.json"
    return {
        "incoming_phone_numbers": [format_incoming_number(n, account_sid) for n in numbers],
        "page": 0,
        "page_size": 50,
        "start": 0,
        "end": len(numbers) - 1 if numbers else 0,
        "uri": uri,
        "first_page_uri": f"{uri}?Page=0&PageSize=50",
        "next_page_uri": None,
    }


def format_port_order(order: SandboxPortRequest) -> dict[str, Any]:
    return {
        "port_in_request_sid": order.external_id,
        "url": f"/v1/Porting/Orders/{order.external_id}",
        "account_sid": order.metadata_json.get("account_sid", ""),
        "notification_emails": order.metadata_json.get("notification_emails", []),
        "target_port_in_date": order.foc_date.isoformat() if order.foc_date else None,
        "target_port_in_time_range_start": "08:00",
        "target_port_in_time_range_end": "17:00",
        "port_in_request_status": order.status,
        "losing_carrier_information": order.loa_info,
        "phone_numbers": order.numbers,
        "documents": [],
        "date_created": order.created_at.isoformat() if order.created_at else None,
        "date_updated": order.created_at.isoformat() if order.created_at else None,
    }


def format_brand(brand: SandboxBrand) -> dict[str, Any]:
    return {
        "sid": brand.external_id,
        "account_sid": brand.brand_data.get("account_sid", ""),
        "customer_profile_bundle_sid": brand.brand_data.get("customer_profile_bundle_sid"),
        "a2p_profile_bundle_sid": brand.brand_data.get("a2p_profile_bundle_sid"),
        "brand_type": brand.brand_data.get("brand_type", "STANDARD"),
        "status": brand.status,
        "tcr_id": f"BN{brand.external_id[-10:]}",
        "failure_reason": None,
        "url": f"/v1/a2p/BrandRegistrations/{brand.external_id}",
        "brand_score": 75,
        "date_created": brand.created_at.isoformat() if brand.created_at else None,
        "date_updated": brand.created_at.isoformat() if brand.created_at else None,
    }


def format_campaign(campaign: SandboxCampaign, messaging_service_sid: str) -> dict[str, Any]:
    return {
        "sid": campaign.external_id,
        "account_sid": campaign.raw_request.get("account_sid", ""),
        "brand_registration_sid": campaign.raw_request.get("BrandRegistrationSid"),
        "messaging_service_sid": messaging_service_sid,
        "description": campaign.description,
        "message_samples": campaign.sample_messages,
        "us_app_to_person_usecase": campaign.use_case,
        "has_embedded_links": campaign.raw_request.get("HasEmbeddedLinks", False),
        "has_embedded_phone": campaign.raw_request.get("HasEmbeddedPhone", False),
        "campaign_status": campaign.status,
        "campaign_id": f"C{campaign.external_id[-10:]}",
        "is_externally_registered": False,
        "rate_limits": {"att": {"mps": 10, "msg_class": "A"}},
        "date_created": campaign.created_at.isoformat() if campaign.created_at else None,
        "date_updated": campaign.created_at.isoformat() if campaign.created_at else None,
        "url": (f"/v1/Services/{messaging_service_sid}/Compliance/Usa2p/{campaign.external_id}"),
    }
