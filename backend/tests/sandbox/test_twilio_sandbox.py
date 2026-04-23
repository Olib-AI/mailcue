"""Extended Twilio sandbox tests: voice, numbers, porting, A2P."""

from __future__ import annotations

import asyncio

from httpx import AsyncClient

from tests.conftest import basic_auth_header

TWILIO_PREFIX = "/sandbox/twilio/2010-04-01/Accounts"


def _auth(provider: dict) -> dict[str, str]:
    sid = provider["credentials"]["account_sid"]
    token = provider["credentials"]["auth_token"]
    return {"Authorization": basic_auth_header(sid, token)}


def _url(provider: dict, path: str = "") -> str:
    sid = provider["credentials"]["account_sid"]
    return f"{TWILIO_PREFIX}/{sid}{path}"


# ── MMS (multimedia) ─────────────────────────────────────────────────


async def test_send_mms_with_media(client: AsyncClient, twilio_provider: dict):
    resp = await client.post(
        _url(twilio_provider, "/Messages.json"),
        json={
            "To": "+15551234567",
            "From": "+15559876543",
            "Body": "Check this out",
            "MediaUrl": ["https://example.com/image1.png", "https://example.com/image2.png"],
        },
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["num_media"] == "2"


async def test_send_form_encoded(client: AsyncClient, twilio_provider: dict):
    resp = await client.post(
        _url(twilio_provider, "/Messages.json"),
        data={"To": "+15551234567", "From": "+15559876543", "Body": "form test"},
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 200
    assert resp.json()["body"] == "form test"


# ── Available numbers search ─────────────────────────────────────────


async def test_available_numbers_local(client: AsyncClient, twilio_provider: dict):
    resp = await client.get(
        _url(twilio_provider, "/AvailablePhoneNumbers/US/Local.json"),
        params={"AreaCode": "415", "PageSize": 10},
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "available_phone_numbers" in data
    assert len(data["available_phone_numbers"]) == 10
    first = data["available_phone_numbers"][0]
    assert first["phone_number"].startswith("+1415")
    assert first["iso_country"] == "US"
    assert first["capabilities"]["voice"] is True


async def test_available_tollfree(client: AsyncClient, twilio_provider: dict):
    resp = await client.get(
        _url(twilio_provider, "/AvailablePhoneNumbers/US/TollFree.json"),
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 200
    nums = resp.json()["available_phone_numbers"]
    assert any(
        n["phone_number"].startswith("+1800") or n["phone_number"].startswith("+1833")
        for n in nums
    )


# ── Purchase / release numbers ───────────────────────────────────────


async def test_purchase_and_release_number(client: AsyncClient, twilio_provider: dict):
    # Search
    search = await client.get(
        _url(twilio_provider, "/AvailablePhoneNumbers/US/Local.json"),
        params={"AreaCode": "212", "PageSize": 1},
        headers=_auth(twilio_provider),
    )
    e164 = search.json()["available_phone_numbers"][0]["phone_number"]
    # Purchase
    buy = await client.post(
        _url(twilio_provider, "/IncomingPhoneNumbers.json"),
        json={
            "PhoneNumber": e164,
            "FriendlyName": "My test number",
            "SmsUrl": "https://app.example.com/sms",
            "VoiceUrl": "https://app.example.com/voice",
        },
        headers=_auth(twilio_provider),
    )
    assert buy.status_code == 200
    bought = buy.json()
    assert bought["sid"].startswith("PN")
    assert bought["phone_number"] == e164

    # List
    listing = await client.get(
        _url(twilio_provider, "/IncomingPhoneNumbers.json"),
        headers=_auth(twilio_provider),
    )
    assert listing.status_code == 200
    assert any(n["phone_number"] == e164 for n in listing.json()["incoming_phone_numbers"])

    # Update webhook URL
    upd = await client.post(
        _url(twilio_provider, f"/IncomingPhoneNumbers/{bought['sid']}.json"),
        json={"SmsUrl": "https://app.example.com/sms2"},
        headers=_auth(twilio_provider),
    )
    assert upd.status_code == 200
    assert upd.json()["sms_url"] == "https://app.example.com/sms2"

    # Release
    rel = await client.delete(
        _url(twilio_provider, f"/IncomingPhoneNumbers/{bought['sid']}.json"),
        headers=_auth(twilio_provider),
    )
    assert rel.status_code == 204


# ── Calls + TwiML interpreter ────────────────────────────────────────


async def test_create_call_with_status_callback(client: AsyncClient, twilio_provider: dict):
    resp = await client.post(
        _url(twilio_provider, "/Calls.json"),
        json={
            "To": "+15551111111",
            "From": "+15559999999",
            "Url": "https://example.com/twiml",
            "StatusCallback": "https://example.com/status",
        },
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sid"].startswith("CA")
    assert data["status"] == "queued"
    assert data["to"] == "+15551111111"


async def test_list_and_fetch_call(client: AsyncClient, twilio_provider: dict):
    create = await client.post(
        _url(twilio_provider, "/Calls.json"),
        json={"To": "+15552222222", "From": "+15553333333"},
        headers=_auth(twilio_provider),
    )
    sid = create.json()["sid"]

    lst = await client.get(
        _url(twilio_provider, "/Calls.json"),
        headers=_auth(twilio_provider),
    )
    assert lst.status_code == 200
    assert any(c["sid"] == sid for c in lst.json()["calls"])

    fetch = await client.get(
        _url(twilio_provider, f"/Calls/{sid}.json"),
        headers=_auth(twilio_provider),
    )
    assert fetch.status_code == 200
    assert fetch.json()["sid"] == sid


async def test_update_call_hangup(client: AsyncClient, twilio_provider: dict):
    create = await client.post(
        _url(twilio_provider, "/Calls.json"),
        json={"To": "+15554444444", "From": "+15555555555"},
        headers=_auth(twilio_provider),
    )
    sid = create.json()["sid"]
    upd = await client.post(
        _url(twilio_provider, f"/Calls/{sid}.json"),
        json={"Status": "completed"},
        headers=_auth(twilio_provider),
    )
    assert upd.status_code == 200
    assert upd.json()["status"] == "completed"


# ── Porting ───────────────────────────────────────────────────────────


async def test_port_order_lifecycle(client: AsyncClient, twilio_provider: dict):
    resp = await client.post(
        "/sandbox/twilio/v1/Porting/Orders",
        json={
            "phone_numbers": ["+15551234567"],
            "notification_emails": ["ops@example.com"],
            "loa_info": {"first_name": "A", "last_name": "B"},
        },
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["port_in_request_sid"].startswith("PO")
    assert data["port_in_request_status"] in {"submitted", "pending-loa", "approved"}

    # Poll for lifecycle progression
    await asyncio.sleep(0.3)
    fetch = await client.get(
        f"/sandbox/twilio/v1/Porting/Orders/{data['port_in_request_sid']}",
        headers=_auth(twilio_provider),
    )
    assert fetch.status_code == 200
    assert fetch.json()["port_in_request_status"] in {
        "submitted",
        "pending-loa",
        "approved",
        "foc-scheduled",
        "completed",
    }


# ── A2P brand + campaign ─────────────────────────────────────────────


async def test_brand_and_campaign_registration(client: AsyncClient, twilio_provider: dict):
    # Create CustomerProfile first
    prof = await client.post(
        "/sandbox/twilio/v1/CustomerProfiles",
        json={"FriendlyName": "ACME", "Email": "ops@acme.com"},
        headers=_auth(twilio_provider),
    )
    assert prof.status_code == 200
    profile_sid = prof.json()["sid"]
    assert profile_sid.startswith("BU")

    # Create brand
    brand = await client.post(
        "/sandbox/twilio/v1/a2p/BrandRegistrations",
        json={
            "CustomerProfileBundleSid": profile_sid,
            "A2PProfileBundleSid": profile_sid,
            "BrandType": "STANDARD",
            "FriendlyName": "ACME Brand",
        },
        headers=_auth(twilio_provider),
    )
    assert brand.status_code == 200
    brand_sid = brand.json()["sid"]

    # Wait for approval
    await asyncio.sleep(0.2)
    fetch = await client.get(
        f"/sandbox/twilio/v1/a2p/BrandRegistrations/{brand_sid}",
        headers=_auth(twilio_provider),
    )
    assert fetch.json()["status"] in {"PENDING", "APPROVED"}

    # Campaign
    camp = await client.post(
        "/sandbox/twilio/v1/Services/MGXYZ/Compliance/Usa2p",
        json={
            "BrandRegistrationSid": brand_sid,
            "Description": "Order updates",
            "MessageSamples": ["Your order shipped", "Your delivery arrives today"],
            "UsAppToPersonUsecase": "MARKETING",
        },
        headers=_auth(twilio_provider),
    )
    assert camp.status_code == 200
    camp_sid = camp.json()["sid"]

    await asyncio.sleep(0.2)
    fetch = await client.get(
        f"/sandbox/twilio/v1/Services/MGXYZ/Compliance/Usa2p/{camp_sid}",
        headers=_auth(twilio_provider),
    )
    assert fetch.json()["campaign_status"] in {"PENDING", "APPROVED"}


# ── Capability matrix ────────────────────────────────────────────────


async def test_capability_matrix(client: AsyncClient):
    resp = await client.get("/sandbox/providers/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert "twilio" in data["providers"]
    twilio = data["providers"]["twilio"]
    for cap in ("sms", "mms", "voice", "porting", "tcr", "number_search"):
        assert twilio[cap] is True


# ── Account resource fetch (verify_credentials probe) ────────────────


async def test_account_fetch(client: AsyncClient, twilio_provider: dict):
    sid = twilio_provider["credentials"]["account_sid"]
    resp = await client.get(
        f"{TWILIO_PREFIX}/{sid}.json",
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sid"] == sid
    assert body["status"] == "active"
    assert body["type"] == "Full"
    assert body["owner_account_sid"] == sid
    assert body["uri"] == f"/2010-04-01/Accounts/{sid}.json"
    # ``subresource_uris`` must include ``messages`` + ``calls`` so the
    # Twilio SDK's auto-generated Account resource hydrates properly.
    assert "messages" in body["subresource_uris"]
    assert "calls" in body["subresource_uris"]


async def test_account_fetch_unauth(client: AsyncClient, twilio_provider: dict):
    sid = twilio_provider["credentials"]["account_sid"]
    resp = await client.get(
        f"{TWILIO_PREFIX}/{sid}.json",
        headers={"Authorization": basic_auth_header(sid, "wrong")},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 20003


# ── Available numbers capability shape ───────────────────────────────


async def test_available_numbers_capabilities_shape(client: AsyncClient, twilio_provider: dict):
    """Real Twilio returns ``capabilities`` with mixed case keys:
    ``voice`` lowercase, ``SMS``/``MMS`` uppercase, ``fax`` lowercase.
    """
    resp = await client.get(
        _url(twilio_provider, "/AvailablePhoneNumbers/US/Local.json"),
        params={"AreaCode": "415", "PageSize": 1},
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 200
    first = resp.json()["available_phone_numbers"][0]
    caps = first["capabilities"]
    assert set(caps.keys()) == {"voice", "SMS", "MMS", "fax"}
    assert isinstance(caps["voice"], bool)
    assert isinstance(caps["SMS"], bool)
    assert isinstance(caps["MMS"], bool)
    assert isinstance(caps["fax"], bool)
