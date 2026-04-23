"""Format sandbox data into Bandwidth response shapes (JSON + XML)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree as ET

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
    return (ts or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_message_id() -> str:
    return uuid.uuid4().hex


def new_call_id() -> str:
    return "c-" + uuid.uuid4().hex[:32]


def new_order_id() -> str:
    return uuid.uuid4().hex[:36]


def new_port_id() -> str:
    return uuid.uuid4().hex[:36]


def new_brand_id() -> str:
    return "B" + uuid.uuid4().hex[:15].upper()


def new_campaign_id() -> str:
    return "C" + uuid.uuid4().hex[:15].upper()


def format_message(message: SandboxMessage, account_id: str) -> dict[str, Any]:
    media = message.metadata_json.get("media_urls", []) or []
    return {
        "id": message.external_id or new_message_id(),
        "time": _isoformat(message.created_at),
        "to": message.metadata_json.get("to", []),
        "from": message.metadata_json.get("from", message.sender),
        "text": message.content or "",
        "applicationId": message.metadata_json.get("application_id", ""),
        "media": media,
        "tag": message.metadata_json.get("tag"),
        "owner": message.metadata_json.get("from", message.sender),
        "direction": "out" if message.direction == "outbound" else "in",
        "segmentCount": 1,
        "priority": "default",
        "expiration": None,
        "messageStatus": "queued" if message.direction == "outbound" else "received",
    }


def format_call(call: SandboxCall, account_id: str) -> dict[str, Any]:
    return {
        "callId": call.external_id,
        "accountId": account_id,
        "applicationId": call.metadata_json.get("application_id", ""),
        "to": call.to_number,
        "from": call.from_number,
        "direction": "outbound" if call.direction == "outbound" else "inbound",
        "state": call.status,
        "enqueuedTime": _isoformat(call.created_at),
        "startTime": _isoformat(call.answered_at) if call.answered_at else None,
        "endTime": _isoformat(call.ended_at) if call.ended_at else None,
        "answerTime": _isoformat(call.answered_at) if call.answered_at else None,
        "answerUrl": call.answer_url,
        "answerMethod": call.answer_method,
        "disconnectUrl": call.metadata_json.get("disconnect_url"),
        "disconnectMethod": call.metadata_json.get("disconnect_method", "POST"),
        "callUrl": f"https://voice.bandwidth.com/api/v2/accounts/{account_id}/calls/{call.external_id}",
        "duration": str(call.duration_seconds) if call.duration_seconds else None,
    }


def format_brand(brand: SandboxBrand) -> dict[str, Any]:
    raw = brand.raw_request
    return {
        "accountBrandId": brand.external_id,
        "tcrBrandId": f"BRD{brand.external_id[-8:]}",
        "status": brand.status,
        "brand": {
            "displayName": raw.get("displayName", ""),
            "companyName": raw.get("companyName", raw.get("displayName", "")),
            "ein": raw.get("ein"),
            "email": raw.get("email", ""),
            "entityType": raw.get("entityType", "PRIVATE_PROFIT"),
            "brandRelationship": raw.get("brandRelationship", "BASIC_ACCOUNT"),
            "vertical": raw.get("vertical", "TECHNOLOGY"),
            "country": raw.get("country", "US"),
        },
        "createDate": _isoformat(brand.created_at),
        "updateDate": _isoformat(brand.created_at),
        "failureReason": None,
    }


def format_campaign(campaign: SandboxCampaign) -> dict[str, Any]:
    raw = campaign.raw_request
    return {
        "accountCampaignId": campaign.external_id,
        "tcrCampaignId": f"CMP{campaign.external_id[-8:]}",
        "status": campaign.status,
        "brandId": raw.get("brandId"),
        "usecase": campaign.use_case,
        "description": campaign.description,
        "sampleMessages": campaign.sample_messages,
        "hasEmbeddedLinks": bool(raw.get("hasEmbeddedLinks", False)),
        "hasEmbeddedPhone": bool(raw.get("hasEmbeddedPhone", False)),
        "subscriberOptIn": bool(raw.get("subscriberOptIn", True)),
        "subscriberOptOut": bool(raw.get("subscriberOptOut", True)),
        "subscriberHelp": bool(raw.get("subscriberHelp", True)),
        "createDate": _isoformat(campaign.created_at),
        "updateDate": _isoformat(campaign.created_at),
    }


# ── XML formatters ──────────────────────────────────────────────────────────


def format_available_numbers_xml(numbers: list[AvailableNumber]) -> str:
    root = ET.Element("SearchResult")
    ET.SubElement(root, "ResultCount").text = str(len(numbers))
    tns = ET.SubElement(root, "TelephoneNumberList")
    for n in numbers:
        tn = ET.SubElement(tns, "TelephoneNumber")
        # Bandwidth uses 10-digit/national format without + in number search responses
        stripped = n.e164.lstrip("+")
        if stripped.startswith("1"):
            stripped = stripped[1:]
        tn.text = stripped
    return _xml_declaration() + ET.tostring(root, encoding="unicode")


def format_order_xml(order: SandboxNumberOrder, numbers: list[str]) -> str:
    root = ET.Element("OrderResponse")
    o = ET.SubElement(root, "Order")
    ET.SubElement(o, "OrderCreateDate").text = _isoformat(order.created_at)
    ET.SubElement(o, "id").text = order.external_id
    ET.SubElement(o, "OrderStatus").text = order.status
    existing = ET.SubElement(o, "ExistingTelephoneNumberOrderType")
    tn_list = ET.SubElement(existing, "TelephoneNumberList")
    for n in numbers:
        stripped = n.lstrip("+")
        if stripped.startswith("1"):
            stripped = stripped[1:]
        ET.SubElement(tn_list, "TelephoneNumber").text = stripped
    ET.SubElement(root, "OrderCompleteDate").text = _isoformat(order.created_at)
    return _xml_declaration() + ET.tostring(root, encoding="unicode")


def format_port_in_xml(order: SandboxPortRequest) -> str:
    root = ET.Element("LnpOrderResponse")
    ET.SubElement(root, "OrderId").text = order.external_id
    ET.SubElement(root, "Status").text = order.status
    ET.SubElement(root, "CustomerOrderId").text = order.metadata_json.get("customer_order_id", "")
    tn_list = ET.SubElement(root, "ListOfPhoneNumbers")
    for n in order.numbers:
        stripped = n.lstrip("+")
        if stripped.startswith("1"):
            stripped = stripped[1:]
        ET.SubElement(tn_list, "PhoneNumber").text = stripped
    ET.SubElement(root, "LoaType").text = str(order.loa_info.get("type", "CARRIER"))
    return _xml_declaration() + ET.tostring(root, encoding="unicode")


def format_messaging_settings_xml(number: SandboxPhoneNumber) -> str:
    root = ET.Element("MessagingSettings")
    ET.SubElement(root, "HttpSettings")  # placeholder
    app_id = ET.SubElement(root, "ApplicationSettings")
    ET.SubElement(app_id, "ApplicationId").text = number.metadata_json.get(
        "messaging_application_id", ""
    )
    return _xml_declaration() + ET.tostring(root, encoding="unicode")


def format_voice_settings_xml(number: SandboxPhoneNumber) -> str:
    root = ET.Element("VoiceSettings")
    app_settings = ET.SubElement(root, "ApplicationSettings")
    voice_app_id = number.metadata_json.get("voice_application_id", "")
    # Emit the V2 voice tag (fase + real Bandwidth dashboard API);
    # keep the legacy ApplicationId tag alongside it so older clients
    # that read back the settings before re-PUT-ing still parse
    # correctly.
    ET.SubElement(app_settings, "HttpVoiceV2AppId").text = voice_app_id
    ET.SubElement(app_settings, "ApplicationId").text = voice_app_id
    return _xml_declaration() + ET.tostring(root, encoding="unicode")


def _xml_declaration() -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>'


def parse_order_xml(body: str) -> dict[str, Any]:
    """Parse a <Order> XML body from POST /orders."""
    try:
        root = ET.fromstring(body.strip())
    except ET.ParseError:
        return {}

    order_elem = root if root.tag == "Order" else (root.find("Order") or root)

    numbers: list[str] = []
    for tn in order_elem.iter("TelephoneNumber"):
        txt = (tn.text or "").strip()
        if txt:
            numbers.append("+1" + txt if not txt.startswith("+") else txt)
    name = order_elem.findtext("Name") or ""
    return {"name": name, "numbers": numbers, "raw_xml": body}


def parse_port_in_xml(body: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(body.strip())
    except ET.ParseError:
        return {}
    numbers: list[str] = []
    for pn in root.iter("PhoneNumber"):
        txt = (pn.text or "").strip()
        if txt:
            numbers.append("+1" + txt if not txt.startswith("+") else txt)
    loa_type = root.findtext("LoaType") or "CARRIER"
    customer_order = root.findtext("CustomerOrderId") or ""
    return {
        "numbers": numbers,
        "loa_info": {"type": loa_type},
        "customer_order_id": customer_order,
    }


def parse_available_numbers_query(params: dict[str, Any]) -> dict[str, Any]:
    """Map Bandwidth's dashboard search params to our seed-table filters."""
    area = params.get("areaCode")
    if isinstance(area, list):
        area = area[0] if area else None
    contains = params.get("lata")
    if isinstance(contains, list):
        contains = contains[0] if contains else None
    quantity_raw = params.get("quantity")
    if isinstance(quantity_raw, list):
        quantity_raw = quantity_raw[0] if quantity_raw else None
    try:
        quantity = int(quantity_raw) if quantity_raw else 50
    except (TypeError, ValueError):
        quantity = 50
    return {"area_code": area, "contains": contains, "quantity": quantity}
