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
        "/sandbox/vonage/number/search",
        params={**_api_params(vonage_provider), "country": "US"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0
    assert all("msisdn" in n for n in data["numbers"])


async def test_number_search_with_features(client: AsyncClient, vonage_provider: dict):
    resp = await client.get(
        "/sandbox/vonage/number/search",
        params={
            **_api_params(vonage_provider),
            "country": "US",
            "size": 5,
            "features": "SMS,VOICE",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0
    # features must be a list of strings per real Vonage shape
    for n in data["numbers"]:
        assert isinstance(n["features"], list)
        assert "msisdn" in n
        assert "cost" in n
        assert "type" in n


async def test_number_search_legacy_410(client: AsyncClient, vonage_provider: dict):
    """Old path-parameterised /number/search/{country} returns 410."""
    resp = await client.get(
        "/sandbox/vonage/number/search/US",
        params=_api_params(vonage_provider),
    )
    assert resp.status_code == 410


async def test_number_buy_and_cancel(client: AsyncClient, vonage_provider: dict):
    search = await client.get(
        "/sandbox/vonage/number/search",
        params={**_api_params(vonage_provider), "country": "US"},
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


# ── Messages API v1 — string-form to/from (Fix #2) ───────────────────


async def test_messages_send_sms_string_to_from(client: AsyncClient, vonage_provider: dict):
    """Real Vonage accepts bare-string ``to``/``from`` on SMS channel."""
    resp = await client.post(
        "/sandbox/vonage/v1/messages",
        json={
            "message_type": "text",
            "channel": "sms",
            "to": "15551234567",
            "from": "Vonage",
            "text": "Hello (string form)",
        },
        headers=_bearer(vonage_provider),
    )
    assert resp.status_code == 202
    assert "message_uuid" in resp.json()


async def test_messages_send_sms_mixed_shapes(client: AsyncClient, vonage_provider: dict):
    """Object ``to`` + string ``from`` (and vice-versa) both work."""
    resp = await client.post(
        "/sandbox/vonage/v1/messages",
        json={
            "message_type": "text",
            "channel": "sms",
            "to": {"type": "sms", "number": "15551234567"},
            "from": "15559876543",
            "text": "mixed shapes",
        },
        headers=_bearer(vonage_provider),
    )
    assert resp.status_code == 202


async def test_messages_send_invalid_to_422(client: AsyncClient, vonage_provider: dict):
    """``to`` as a list (wrong shape) must 422 in Vonage-shaped body."""
    resp = await client.post(
        "/sandbox/vonage/v1/messages",
        json={
            "message_type": "text",
            "channel": "sms",
            "to": ["15551234567"],
            "from": "15559876543",
            "text": "bad",
        },
        headers=_bearer(vonage_provider),
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["title"] == "Invalid request body"


# ── Account get-balance (Fix #4 / verify_credentials) ─────────────────


async def test_account_get_balance(client: AsyncClient, vonage_provider: dict):
    resp = await client.get(
        "/sandbox/vonage/account/get-balance",
        params=_api_params(vonage_provider),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["value"], (int, float))
    assert "autoReload" in body


async def test_account_get_balance_unauth(client: AsyncClient, vonage_provider: dict):
    resp = await client.get(
        "/sandbox/vonage/account/get-balance",
        params={"api_key": "wrong", "api_secret": "bad"},
    )
    assert resp.status_code == 401
