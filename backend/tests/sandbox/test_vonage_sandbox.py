"""End-to-end tests for Vonage sandbox."""

from __future__ import annotations

from httpx import AsyncClient


def _bearer(provider: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {provider['credentials']['messages_token']}"}


def _api_params(provider: dict) -> dict[str, str]:
    return {
        "api_key": provider["credentials"]["api_key"],
        "api_secret": provider["credentials"]["api_secret"],
    }


# ── Messages API v1 ──────────────────────────────────────────────────


async def test_messages_send_sms(client: AsyncClient, vonage_provider: dict):
    resp = await client.post(
        "/sandbox/vonage/v1/messages",
        json={
            "message_type": "text",
            "channel": "sms",
            "to": {"type": "sms", "number": "15551234567"},
            "from": {"type": "sms", "number": "Vonage"},
            "text": "Hello",
        },
        headers=_bearer(vonage_provider),
    )
    assert resp.status_code == 202
    assert "message_uuid" in resp.json()


async def test_messages_send_mms(client: AsyncClient, vonage_provider: dict):
    resp = await client.post(
        "/sandbox/vonage/v1/messages",
        json={
            "message_type": "image",
            "channel": "mms",
            "to": {"type": "mms", "number": "15551234567"},
            "from": {"type": "mms", "number": "15559876543"},
            "image": {"url": "https://example.com/img.png"},
            "text": "Caption",
        },
        headers=_bearer(vonage_provider),
    )
    assert resp.status_code == 202


async def test_messages_unauth(client: AsyncClient, vonage_provider: dict):
    resp = await client.post(
        "/sandbox/vonage/v1/messages",
        json={"message_type": "text", "channel": "sms", "to": {}, "from": {}, "text": "x"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


# ── Voice API v1 ─────────────────────────────────────────────────────


async def test_create_call(client: AsyncClient, vonage_provider: dict):
    resp = await client.post(
        "/sandbox/vonage/v1/calls",
        json={
            "to": [{"type": "phone", "number": "15551234567"}],
            "from": {"type": "phone", "number": "15559876543"},
            "ncco": [{"action": "talk", "text": "Hello from Vonage"}],
        },
        headers=_bearer(vonage_provider),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["uuid"]
    assert data["status"] == "started"


async def test_fetch_call(client: AsyncClient, vonage_provider: dict):
    create = await client.post(
        "/sandbox/vonage/v1/calls",
        json={
            "to": [{"type": "phone", "number": "15551234567"}],
            "from": {"type": "phone", "number": "15559876543"},
            "answer_url": ["https://app.example.com/answer"],
        },
        headers=_bearer(vonage_provider),
    )
    uuid = create.json()["uuid"]
    fetch = await client.get(
        f"/sandbox/vonage/v1/calls/{uuid}",
        headers=_bearer(vonage_provider),
    )
    assert fetch.status_code == 200
    assert fetch.json()["uuid"] == uuid


# ── Numbers ──────────────────────────────────────────────────────────


async def test_number_search(client: AsyncClient, vonage_provider: dict):
    resp = await client.get(
        "/sandbox/vonage/number/search/US",
        params=_api_params(vonage_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0
    assert all("msisdn" in n for n in data["numbers"])


async def test_number_buy_and_cancel(client: AsyncClient, vonage_provider: dict):
    search = await client.get(
        "/sandbox/vonage/number/search/US",
        params=_api_params(vonage_provider),
    )
    msisdn = search.json()["numbers"][0]["msisdn"]
    buy = await client.post(
        "/sandbox/vonage/number/buy",
        params={**_api_params(vonage_provider), "country": "US", "msisdn": msisdn},
    )
    assert buy.status_code == 200
    assert buy.json()["error-code"] == "200"

    cancel = await client.post(
        "/sandbox/vonage/number/cancel",
        params={**_api_params(vonage_provider), "country": "US", "msisdn": msisdn},
    )
    assert cancel.status_code == 200


# ── Capabilities: Vonage does NOT support porting/TCR ────────────────


async def test_vonage_no_porting(client: AsyncClient):
    resp = await client.get("/sandbox/providers/capabilities")
    v = resp.json()["providers"]["vonage"]
    assert v["porting"] is False
    assert v["tcr"] is False
    assert v["sms"] is True
    assert v["voice"] is True


async def test_port_endpoint_returns_404(client: AsyncClient, vonage_provider: dict):
    resp = await client.post(
        "/sandbox/vonage/number/port",
        headers=_bearer(vonage_provider),
    )
    assert resp.status_code == 404
