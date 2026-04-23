"""End-to-end tests for Bandwidth sandbox."""

from __future__ import annotations

import asyncio

from httpx import AsyncClient

from tests.conftest import basic_auth_header


def _auth(provider: dict) -> dict[str, str]:
    creds = provider["credentials"]
    return {"Authorization": basic_auth_header(creds["username"], creds["password"])}


def _acct(provider: dict) -> str:
    return provider["credentials"]["account_id"]


# ── Messaging v2 ─────────────────────────────────────────────────────


async def test_send_message(client: AsyncClient, bandwidth_provider: dict):
    acc = _acct(bandwidth_provider)
    resp = await client.post(
        f"/sandbox/bandwidth/api/v2/users/{acc}/messages",
        json={
            "applicationId": "msg-app-1",
            "to": ["+15551234567"],
            "from": "+15559876543",
            "text": "Hello from Bandwidth sandbox",
        },
        headers=_auth(bandwidth_provider),
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "id" in data
    assert data["applicationId"] == "msg-app-1"
    assert data["text"] == "Hello from Bandwidth sandbox"
    assert data["direction"] == "out"


async def test_send_mms(client: AsyncClient, bandwidth_provider: dict):
    acc = _acct(bandwidth_provider)
    resp = await client.post(
        f"/sandbox/bandwidth/api/v2/users/{acc}/messages",
        json={
            "applicationId": "msg-app-1",
            "to": ["+15551234567"],
            "from": "+15559876543",
            "text": "With media",
            "media": ["https://example.com/a.png"],
        },
        headers=_auth(bandwidth_provider),
    )
    assert resp.status_code == 202
    assert resp.json()["media"] == ["https://example.com/a.png"]


async def test_invalid_auth(client: AsyncClient, bandwidth_provider: dict):
    acc = _acct(bandwidth_provider)
    resp = await client.post(
        f"/sandbox/bandwidth/api/v2/users/{acc}/messages",
        json={"applicationId": "x", "to": ["+1"], "from": "+1", "text": "hi"},
        headers={"Authorization": basic_auth_header("wrong", "wrong")},
    )
    assert resp.status_code == 401
    assert resp.json()["type"] == "authentication-error"


# ── Voice v2 ─────────────────────────────────────────────────────────


async def test_create_call(client: AsyncClient, bandwidth_provider: dict):
    acc = _acct(bandwidth_provider)
    resp = await client.post(
        f"/sandbox/bandwidth/api/v2/accounts/{acc}/calls",
        json={
            "applicationId": "voice-app-1",
            "from": "+15559999999",
            "to": "+15558888888",
            "answerUrl": "https://app.example.com/bxml/answer",
        },
        headers=_auth(bandwidth_provider),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["callId"].startswith("c-")
    assert data["from"] == "+15559999999"


async def test_list_and_fetch_call(client: AsyncClient, bandwidth_provider: dict):
    acc = _acct(bandwidth_provider)
    create = await client.post(
        f"/sandbox/bandwidth/api/v2/accounts/{acc}/calls",
        json={
            "applicationId": "voice-app-1",
            "from": "+15551",
            "to": "+15552",
            "answerUrl": "https://app.example.com/answer",
        },
        headers=_auth(bandwidth_provider),
    )
    call_id = create.json()["callId"]
    lst = await client.get(
        f"/sandbox/bandwidth/api/v2/accounts/{acc}/calls",
        headers=_auth(bandwidth_provider),
    )
    assert lst.status_code == 200
    assert any(c["callId"] == call_id for c in lst.json())
    fetch = await client.get(
        f"/sandbox/bandwidth/api/v2/accounts/{acc}/calls/{call_id}",
        headers=_auth(bandwidth_provider),
    )
    assert fetch.status_code == 200
    assert fetch.json()["callId"] == call_id


# ── Number search + purchase (XML) ───────────────────────────────────


async def test_available_numbers_xml(client: AsyncClient, bandwidth_provider: dict):
    acc = _acct(bandwidth_provider)
    resp = await client.get(
        f"/sandbox/bandwidth/api/accounts/{acc}/availableNumbers",
        params={"areaCode": "415", "quantity": 5},
        headers=_auth(bandwidth_provider),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    body = resp.text
    assert "<TelephoneNumberList>" in body
    assert body.count("<TelephoneNumber>") >= 5


async def test_available_numbers_toll_free(client: AsyncClient, bandwidth_provider: dict):
    """tollFreeWildCardPattern triggers toll-free search per real API."""
    acc = _acct(bandwidth_provider)
    resp = await client.get(
        f"/sandbox/bandwidth/api/accounts/{acc}/availableNumbers",
        params={"quantity": 3, "tollFreeWildCardPattern": "8**"},
        headers=_auth(bandwidth_provider),
    )
    assert resp.status_code == 200
    assert "<TelephoneNumberList>" in resp.text


async def test_available_numbers_legacy_path_410(client: AsyncClient, bandwidth_provider: dict):
    """Old POST/GET availableTelephoneNumbers path returns 410 Gone."""
    acc = _acct(bandwidth_provider)
    resp = await client.post(
        f"/sandbox/bandwidth/accounts/{acc}/availableTelephoneNumbers",
        params={"areaCode": "415", "quantity": 5},
        headers=_auth(bandwidth_provider),
    )
    assert resp.status_code == 410
    assert "availableNumbers" in resp.text


async def test_verify_credentials_media(client: AsyncClient, bandwidth_provider: dict):
    """GET /api/v2/users/{acc}/media returns 200 + [] for good creds."""
    acc = _acct(bandwidth_provider)
    resp = await client.get(
        f"/sandbox/bandwidth/api/v2/users/{acc}/media",
        headers=_auth(bandwidth_provider),
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_verify_credentials_media_401(client: AsyncClient, bandwidth_provider: dict):
    acc = _acct(bandwidth_provider)
    from tests.conftest import basic_auth_header

    resp = await client.get(
        f"/sandbox/bandwidth/api/v2/users/{acc}/media",
        headers={"Authorization": basic_auth_header("bad", "bad")},
    )
    assert resp.status_code == 401


async def test_dashboard_account_xml(client: AsyncClient, bandwidth_provider: dict):
    acc = _acct(bandwidth_provider)
    resp = await client.get(
        f"/sandbox/bandwidth/api/accounts/{acc}",
        headers=_auth(bandwidth_provider),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert f"<AccountId>{acc}</AccountId>" in resp.text


async def test_order_numbers_xml(client: AsyncClient, bandwidth_provider: dict):
    acc = _acct(bandwidth_provider)
    xml_body = """<?xml version="1.0"?>
<Order>
  <Name>Test Order</Name>
  <ExistingTelephoneNumberOrderType>
    <TelephoneNumberList>
      <TelephoneNumber>2125550000</TelephoneNumber>
    </TelephoneNumberList>
  </ExistingTelephoneNumberOrderType>
</Order>"""
    resp = await client.post(
        f"/sandbox/bandwidth/accounts/{acc}/orders",
        content=xml_body,
        headers={**_auth(bandwidth_provider), "Content-Type": "application/xml"},
    )
    assert resp.status_code == 200
    assert "<OrderResponse>" in resp.text
    assert "<TelephoneNumber>2125550000</TelephoneNumber>" in resp.text


async def test_port_in_xml_lifecycle(client: AsyncClient, bandwidth_provider: dict):
    acc = _acct(bandwidth_provider)
    xml_body = """<?xml version="1.0"?>
<LnpOrder>
  <CustomerOrderId>cust-1</CustomerOrderId>
  <ListOfPhoneNumbers>
    <PhoneNumber>4155555000</PhoneNumber>
  </ListOfPhoneNumbers>
  <LoaType>CARRIER</LoaType>
</LnpOrder>"""
    resp = await client.post(
        f"/sandbox/bandwidth/accounts/{acc}/portIns",
        content=xml_body,
        headers={**_auth(bandwidth_provider), "Content-Type": "application/xml"},
    )
    assert resp.status_code == 200
    assert "<LnpOrderResponse>" in resp.text
    # Extract order id
    import re

    m = re.search(r"<OrderId>([^<]+)</OrderId>", resp.text)
    assert m
    port_id = m.group(1)
    await asyncio.sleep(0.3)
    fetch = await client.get(
        f"/sandbox/bandwidth/accounts/{acc}/portIns/{port_id}",
        headers=_auth(bandwidth_provider),
    )
    assert fetch.status_code == 200
    assert "<LnpOrderResponse>" in fetch.text


# ── CSP (A2P 10DLC) ──────────────────────────────────────────────────


async def test_csp_brand_and_campaign(client: AsyncClient, bandwidth_provider: dict):
    acc = _acct(bandwidth_provider)
    brand = await client.post(
        f"/sandbox/bandwidth/accounts/{acc}/csp/brands",
        json={
            "entityType": "PRIVATE_PROFIT",
            "displayName": "ACME",
            "email": "ops@acme.com",
            "brandRelationship": "BASIC_ACCOUNT",
            "vertical": "TECHNOLOGY",
        },
        headers=_auth(bandwidth_provider),
    )
    assert brand.status_code == 201
    brand_id = brand.json()["accountBrandId"]

    await asyncio.sleep(0.2)
    fetch = await client.get(
        f"/sandbox/bandwidth/accounts/{acc}/csp/brands/{brand_id}",
        headers=_auth(bandwidth_provider),
    )
    assert fetch.json()["status"] in {"PENDING", "APPROVED"}

    camp = await client.post(
        f"/sandbox/bandwidth/accounts/{acc}/csp/campaigns",
        json={
            "brandId": brand_id,
            "usecase": "MARKETING",
            "description": "Orders",
            "sampleMessages": ["msg1", "msg2"],
        },
        headers=_auth(bandwidth_provider),
    )
    assert camp.status_code == 201
    camp_id = camp.json()["accountCampaignId"]
    await asyncio.sleep(0.2)
    fetch = await client.get(
        f"/sandbox/bandwidth/accounts/{acc}/csp/campaigns/{camp_id}",
        headers=_auth(bandwidth_provider),
    )
    assert fetch.json()["status"] in {"PENDING", "APPROVED"}


# ── Messaging application binding ────────────────────────────────────


async def test_messaging_settings_binding(client: AsyncClient, bandwidth_provider: dict):
    acc = _acct(bandwidth_provider)
    # First order a number
    xml_body = """<?xml version="1.0"?>
<Order>
  <ExistingTelephoneNumberOrderType>
    <TelephoneNumberList>
      <TelephoneNumber>3125550000</TelephoneNumber>
    </TelephoneNumberList>
  </ExistingTelephoneNumberOrderType>
</Order>"""
    await client.post(
        f"/sandbox/bandwidth/accounts/{acc}/orders",
        content=xml_body,
        headers={**_auth(bandwidth_provider), "Content-Type": "application/xml"},
    )
    # Bind messaging application
    bind = await client.put(
        f"/sandbox/bandwidth/accounts/{acc}/phonenumbers/3125550000/messagingsettings",
        content="<MessagingSettings><ApplicationSettings><ApplicationId>msg-app-1</ApplicationId></ApplicationSettings></MessagingSettings>",
        headers={**_auth(bandwidth_provider), "Content-Type": "application/xml"},
    )
    assert bind.status_code == 200
    assert "<ApplicationId>msg-app-1</ApplicationId>" in bind.text

    # Release
    rel = await client.delete(
        f"/sandbox/bandwidth/accounts/{acc}/phonenumbers/3125550000",
        headers=_auth(bandwidth_provider),
    )
    assert rel.status_code == 204


# ── Capability matrix includes bandwidth ─────────────────────────────


async def test_capability_includes_bandwidth(client: AsyncClient):
    resp = await client.get("/sandbox/providers/capabilities")
    assert resp.status_code == 200
    bw = resp.json()["providers"]["bandwidth"]
    assert bw["sms"] and bw["voice"] and bw["porting"] and bw["tcr"]
