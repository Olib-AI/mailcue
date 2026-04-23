"""End-to-end tests for Telnyx sandbox with Ed25519 signing."""

from __future__ import annotations

import asyncio
import base64

from httpx import AsyncClient


def _auth(provider: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {provider['credentials']['api_key']}"}


# ── Messages ─────────────────────────────────────────────────────────


async def test_send_sms(client: AsyncClient, telnyx_provider: dict):
    resp = await client.post(
        "/sandbox/telnyx/v2/messages",
        json={
            "from": "+15559876543",
            "to": "+15551234567",
            "text": "Hello from Telnyx sandbox",
            "messaging_profile_id": "prof-123",
        },
        headers=_auth(telnyx_provider),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["record_type"] == "message"
    assert data["type"] == "SMS"
    assert data["text"] == "Hello from Telnyx sandbox"


async def test_send_mms(client: AsyncClient, telnyx_provider: dict):
    resp = await client.post(
        "/sandbox/telnyx/v2/messages",
        json={
            "from": "+15559876543",
            "to": "+15551234567",
            "text": "With image",
            "media_urls": ["https://example.com/img.png"],
        },
        headers=_auth(telnyx_provider),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["type"] == "MMS"


async def test_unauth(client: AsyncClient, telnyx_provider: dict):
    resp = await client.post(
        "/sandbox/telnyx/v2/messages",
        json={"from": "+1", "to": "+1", "text": "x"},
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 401


# ── Public key + Ed25519 signing round-trip ──────────────────────────


async def test_public_key_available(client: AsyncClient, telnyx_provider: dict):
    resp = await client.get(
        "/sandbox/telnyx/v2/public_key",
        headers=_auth(telnyx_provider),
    )
    assert resp.status_code == 200
    pub_b64 = resp.json()["data"]["public_key"]
    # Raw Ed25519 public key is 32 bytes
    assert len(base64.b64decode(pub_b64)) == 32


async def test_ed25519_signer_verifier_roundtrip():
    """Round-trip a payload signature through the real helpers."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.sandbox.providers.telnyx.service import sign_webhook, verify_signature

    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    priv_b64 = base64.b64encode(priv_bytes).decode()
    pub_b64 = base64.b64encode(pub_bytes).decode()

    body = b'{"test":"data"}'
    ts = "1700000000"
    sig = sign_webhook(priv_b64, body, ts)
    assert verify_signature(pub_b64, body, ts, sig) is True
    assert verify_signature(pub_b64, b'{"test":"tampered"}', ts, sig) is False
    assert verify_signature(pub_b64, body, "1700000001", sig) is False


# ── Calls ────────────────────────────────────────────────────────────


async def test_create_call(client: AsyncClient, telnyx_provider: dict):
    resp = await client.post(
        "/sandbox/telnyx/v2/calls",
        json={
            "connection_id": "conn-1",
            "from": "+15559999999",
            "to": "+15558888888",
            "webhook_url": "https://app.example.com/telnyx/webhook",
        },
        headers=_auth(telnyx_provider),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["record_type"] == "call"
    assert data["call_control_id"].startswith("v3:")


async def test_hangup_action(client: AsyncClient, telnyx_provider: dict):
    create = await client.post(
        "/sandbox/telnyx/v2/calls",
        json={"from": "+1", "to": "+2"},
        headers=_auth(telnyx_provider),
    )
    cci = create.json()["data"]["call_control_id"]
    hangup = await client.post(
        f"/sandbox/telnyx/v2/calls/{cci}/actions/hangup",
        headers=_auth(telnyx_provider),
    )
    assert hangup.status_code == 200


# ── Number search + order + release ──────────────────────────────────


async def test_available_numbers(client: AsyncClient, telnyx_provider: dict):
    resp = await client.get(
        "/sandbox/telnyx/v2/available_phone_numbers",
        params={
            "filter[country_code]": "US",
            "filter[phone_number_type]": "local",
            "filter[limit]": 5,
        },
        headers=_auth(telnyx_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["total_results"] > 0


async def test_number_order_and_release(client: AsyncClient, telnyx_provider: dict):
    search = await client.get(
        "/sandbox/telnyx/v2/available_phone_numbers",
        params={"filter[country_code]": "US", "filter[limit]": 1},
        headers=_auth(telnyx_provider),
    )
    e164 = search.json()["data"][0]["phone_number"]
    order = await client.post(
        "/sandbox/telnyx/v2/number_orders",
        json={"phone_numbers": [{"phone_number": e164}]},
        headers=_auth(telnyx_provider),
    )
    assert order.status_code == 201

    owned = await client.get(
        "/sandbox/telnyx/v2/phone_numbers",
        headers=_auth(telnyx_provider),
    )
    assert owned.status_code == 200
    assert any(d["phone_number"] == e164 for d in owned.json()["data"])

    # Release
    pid = next(d["id"] for d in owned.json()["data"] if d["phone_number"] == e164)
    delete = await client.delete(
        f"/sandbox/telnyx/v2/phone_numbers/{pid}",
        headers=_auth(telnyx_provider),
    )
    assert delete.status_code == 200


# ── Porting ──────────────────────────────────────────────────────────


async def test_port_lifecycle(client: AsyncClient, telnyx_provider: dict):
    port = await client.post(
        "/sandbox/telnyx/v2/porting_orders",
        json={"phone_numbers": [{"phone_number": "+15551234567"}]},
        headers=_auth(telnyx_provider),
    )
    assert port.status_code == 201
    port_id = port.json()["data"]["id"]
    await asyncio.sleep(0.3)
    fetch = await client.get(
        f"/sandbox/telnyx/v2/porting_orders/{port_id}",
        headers=_auth(telnyx_provider),
    )
    assert fetch.status_code == 200


# ── Brand + Campaign ─────────────────────────────────────────────────


async def test_brand_and_campaign(client: AsyncClient, telnyx_provider: dict):
    brand = await client.post(
        "/sandbox/telnyx/v2/brand",
        json={
            "entityType": "PRIVATE_PROFIT",
            "displayName": "ACME",
            "email": "ops@acme.com",
            "country": "US",
            "vertical": "TECHNOLOGY",
            "brandRelationship": "BASIC_ACCOUNT",
        },
        headers=_auth(telnyx_provider),
    )
    assert brand.status_code == 201
    brand_id = brand.json()["brandId"]
    await asyncio.sleep(0.2)
    fetch = await client.get(
        f"/sandbox/telnyx/v2/brand/{brand_id}",
        headers=_auth(telnyx_provider),
    )
    assert fetch.json()["status"] in {"PENDING", "APPROVED"}

    camp = await client.post(
        "/sandbox/telnyx/v2/campaign",
        json={
            "brandId": brand_id,
            "usecase": "MARKETING",
            "description": "Marketing",
            "sample1": "Sample one",
            "sample2": "Sample two",
        },
        headers=_auth(telnyx_provider),
    )
    assert camp.status_code == 201
    assert camp.json()["status"] in {"PENDING", "APPROVED"}


# ── Update phone number (messaging profile assignment) ──────────────


async def test_update_phone_number(client: AsyncClient, telnyx_provider: dict):
    search = await client.get(
        "/sandbox/telnyx/v2/available_phone_numbers",
        params={"filter[country_code]": "US", "filter[limit]": 1},
        headers=_auth(telnyx_provider),
    )
    e164 = search.json()["data"][0]["phone_number"]
    await client.post(
        "/sandbox/telnyx/v2/number_orders",
        json={"phone_numbers": [{"phone_number": e164}]},
        headers=_auth(telnyx_provider),
    )
    owned = await client.get(
        "/sandbox/telnyx/v2/phone_numbers",
        headers=_auth(telnyx_provider),
    )
    pid = next(d["id"] for d in owned.json()["data"] if d["phone_number"] == e164)
    update = await client.patch(
        f"/sandbox/telnyx/v2/phone_numbers/{pid}",
        json={"messaging_profile_id": "profile-xyz"},
        headers=_auth(telnyx_provider),
    )
    assert update.status_code == 200
    assert update.json()["data"]["messaging_profile_id"] == "profile-xyz"
