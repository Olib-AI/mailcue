"""Tests for the admin-token-gated simulate-inbound endpoint.

Covers the happy path for every phone provider (Twilio, Bandwidth, Vonage,
Plivo, Telnyx) plus the 403 (bad token) and 404 (unknown provider type)
error paths.  Uses the same ``httpx.AsyncClient`` monkey-patch trick as
``test_webhook_delivery_from_wire.py`` to assert the delivered payload
matches the provider's real inbound wire shape.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, ClassVar

import pytest
from httpx import AsyncClient


@dataclass
class CapturedRequest:
    url: str
    headers: dict[str, str]
    body: bytes


class _StubResponse:
    def __init__(self, status_code: int = 200, body: str = "ok") -> None:
        self.status_code = status_code
        self.text = body


class _StubClient:
    calls: ClassVar[list[CapturedRequest]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    async def __aenter__(self) -> _StubClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        del args

    async def post(
        self,
        url: str,
        *,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> _StubResponse:
        del kwargs
        body = content if content is not None else b""
        _StubClient.calls.append(CapturedRequest(url=url, headers=dict(headers or {}), body=body))
        return _StubResponse(status_code=200, body="ok")


@pytest.fixture()
async def captured(
    _engine_and_session: Any, monkeypatch: pytest.MonkeyPatch
) -> list[CapturedRequest]:
    import app.database as _db
    import app.sandbox.webhook_worker as ww

    _StubClient.calls = []
    monkeypatch.setattr(ww.httpx, "AsyncClient", _StubClient)
    _factory = _engine_and_session[1]
    monkeypatch.setattr(_db, "AsyncSessionLocal", _factory)
    return _StubClient.calls


@pytest.fixture()
def admin_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-admin-token-xyz"
    monkeypatch.setenv("MAILCUE_SANDBOX_ADMIN_TOKEN", token)
    return token


async def _wait_for_calls(calls: list[CapturedRequest], n: int = 1) -> None:
    for _ in range(80):
        if len(calls) >= n:
            return
        await asyncio.sleep(0.01)


async def _register_webhook(client: AsyncClient, provider_id: str, url: str) -> None:
    resp = await client.post(
        f"/api/v1/sandbox/providers/{provider_id}/webhooks",
        json={"url": url, "event_types": ["message.received"]},
    )
    assert resp.status_code == 201


# ── 403 (bad token) + 404 (unknown provider_type) ────────────────────────


async def test_simulate_inbound_rejects_bad_token(
    client: AsyncClient, admin_token: str, twilio_provider: dict
) -> None:
    del admin_token, twilio_provider
    resp = await client.post(
        "/sandbox/admin/providers/simulate-inbound",
        json={
            "provider_type": "twilio",
            "owner_email": "testadmin@mailcue.local",
            "to_number": "+14155550000",
            "from_number": "+15559999000",
            "body": "hello",
        },
        headers={"X-Mailcue-Sandbox-Admin-Token": "nope"},
    )
    assert resp.status_code == 403


async def test_simulate_inbound_404_on_unknown_provider_type(
    client: AsyncClient, admin_token: str
) -> None:
    resp = await client.post(
        "/sandbox/admin/providers/simulate-inbound",
        json={
            "provider_type": "nonexistent",
            "owner_email": "testadmin@mailcue.local",
            "to_number": "+14155550000",
            "from_number": "+15559999000",
            "body": "hello",
        },
        headers={"X-Mailcue-Sandbox-Admin-Token": admin_token},
    )
    assert resp.status_code == 404


async def test_simulate_inbound_404_on_unknown_user(
    client: AsyncClient, admin_token: str, twilio_provider: dict
) -> None:
    del twilio_provider
    resp = await client.post(
        "/sandbox/admin/providers/simulate-inbound",
        json={
            "provider_type": "twilio",
            "owner_email": "ghost@example.com",
            "to_number": "+14155550000",
            "from_number": "+15559999000",
            "body": "hello",
        },
        headers={"X-Mailcue-Sandbox-Admin-Token": admin_token},
    )
    assert resp.status_code == 404


# ── Happy path per provider ──────────────────────────────────────────────


async def test_simulate_inbound_twilio(
    client: AsyncClient,
    admin_token: str,
    twilio_provider: dict,
    captured: list[CapturedRequest],
) -> None:
    await _register_webhook(client, twilio_provider["id"], "https://hooks.example.com/twilio-in")
    resp = await client.post(
        "/sandbox/admin/providers/simulate-inbound",
        json={
            "provider_type": "twilio",
            "owner_email": "testadmin@mailcue.local",
            "to_number": "+14155550000",
            "from_number": "+15559999000",
            "body": "Hi from test",
        },
        headers={"X-Mailcue-Sandbox-Admin-Token": admin_token},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider_id"] == twilio_provider["id"]
    assert body["webhook_endpoints_fired"] == 1

    # The stored message should be inbound.
    msgs = await client.get(f"/api/v1/sandbox/messages?provider_id={twilio_provider['id']}")
    assert msgs.status_code == 200
    mdata = msgs.json()
    assert any(
        m["direction"] == "inbound" and m["content"] == "Hi from test" for m in mdata["messages"]
    )

    # The webhook fired with Twilio inbound shape.
    await _wait_for_calls(captured)
    assert captured
    cap = captured[0]
    assert cap.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert "X-Twilio-Signature" in cap.headers
    from urllib.parse import parse_qs

    form = {k: v[0] for k, v in parse_qs(cap.body.decode()).items()}
    assert form["From"] == "+15559999000"
    assert form["To"] == "+14155550000"
    assert form["Body"] == "Hi from test"
    assert form["MessageSid"].startswith("SM")
    assert "MessageStatus" not in form  # inbound path has no status


async def test_simulate_inbound_bandwidth(
    client: AsyncClient,
    admin_token: str,
    bandwidth_provider: dict,
    captured: list[CapturedRequest],
) -> None:
    await _register_webhook(client, bandwidth_provider["id"], "https://hooks.example.com/bw-in")
    resp = await client.post(
        "/sandbox/admin/providers/simulate-inbound",
        json={
            "provider_type": "bandwidth",
            "owner_email": "testadmin@mailcue.local",
            "to_number": "+14155550001",
            "from_number": "+15559999001",
            "body": "bw hi",
        },
        headers={"X-Mailcue-Sandbox-Admin-Token": admin_token},
    )
    assert resp.status_code == 200
    await _wait_for_calls(captured)
    cap = captured[0]
    payload = json.loads(cap.body)
    assert isinstance(payload, list)
    entry = payload[0]
    assert entry["type"] == "message-received"
    assert entry["to"] == "+14155550001"
    assert entry["message"]["from"] == "+15559999001"
    assert entry["message"]["text"] == "bw hi"
    assert entry["message"]["direction"] == "in"
    assert entry["message"]["to"] == ["+14155550001"]


async def test_simulate_inbound_vonage(
    client: AsyncClient,
    admin_token: str,
    vonage_provider: dict,
    captured: list[CapturedRequest],
) -> None:
    await _register_webhook(client, vonage_provider["id"], "https://hooks.example.com/vonage-in")
    resp = await client.post(
        "/sandbox/admin/providers/simulate-inbound",
        json={
            "provider_type": "vonage",
            "owner_email": "testadmin@mailcue.local",
            "to_number": "+14155550002",
            "from_number": "+15559999002",
            "body": "vonage hi",
        },
        headers={"X-Mailcue-Sandbox-Admin-Token": admin_token},
    )
    assert resp.status_code == 200
    await _wait_for_calls(captured)
    cap = captured[0]
    payload = json.loads(cap.body)
    assert payload["channel"] == "sms"
    assert payload["to"] == {"type": "sms", "number": "+14155550002"}
    assert payload["from"] == {"type": "sms", "number": "+15559999002"}
    assert payload["text"] == "vonage hi"
    assert "message_uuid" in payload


async def test_simulate_inbound_plivo(
    client: AsyncClient,
    admin_token: str,
    plivo_provider: dict,
    captured: list[CapturedRequest],
) -> None:
    await _register_webhook(client, plivo_provider["id"], "https://hooks.example.com/plivo-in")
    resp = await client.post(
        "/sandbox/admin/providers/simulate-inbound",
        json={
            "provider_type": "plivo",
            "owner_email": "testadmin@mailcue.local",
            "to_number": "+14155550003",
            "from_number": "+15559999003",
            "body": "plivo hi",
        },
        headers={"X-Mailcue-Sandbox-Admin-Token": admin_token},
    )
    assert resp.status_code == 200
    await _wait_for_calls(captured)
    cap = captured[0]
    assert cap.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert "X-Plivo-Signature-V3" in cap.headers
    from urllib.parse import parse_qs

    form = {k: v[0] for k, v in parse_qs(cap.body.decode()).items()}
    assert form["From"] == "+15559999003"
    assert form["To"] == "+14155550003"
    assert form["Text"] == "plivo hi"
    assert form["Type"] == "sms"
    assert "Status" not in form


async def test_simulate_inbound_telnyx(
    client: AsyncClient,
    admin_token: str,
    telnyx_provider: dict,
    captured: list[CapturedRequest],
) -> None:
    await _register_webhook(client, telnyx_provider["id"], "https://hooks.example.com/telnyx-in")
    resp = await client.post(
        "/sandbox/admin/providers/simulate-inbound",
        json={
            "provider_type": "telnyx",
            "owner_email": "testadmin@mailcue.local",
            "to_number": "+14155550004",
            "from_number": "+15559999004",
            "body": "telnyx hi",
        },
        headers={"X-Mailcue-Sandbox-Admin-Token": admin_token},
    )
    assert resp.status_code == 200
    await _wait_for_calls(captured)
    cap = captured[0]
    assert "telnyx-signature-ed25519" in cap.headers
    data = json.loads(cap.body)
    assert data["data"]["event_type"] == "message.received"
    payload = data["data"]["payload"]
    assert payload["direction"] == "inbound"
    assert payload["from"]["phone_number"] == "+15559999004"
    assert payload["to"][0]["phone_number"] == "+14155550004"
    assert payload["text"] == "telnyx hi"


# ── Reports webhook_endpoints_fired=0 when no endpoint registered ───────


async def test_simulate_inbound_no_endpoints_fires_zero(
    client: AsyncClient,
    admin_token: str,
    twilio_provider: dict,
    captured: list[CapturedRequest],
) -> None:
    resp = await client.post(
        "/sandbox/admin/providers/simulate-inbound",
        json={
            "provider_type": "twilio",
            "owner_email": "testadmin@mailcue.local",
            "to_number": "+14155550005",
            "from_number": "+15559999005",
            "body": "silent",
        },
        headers={"X-Mailcue-Sandbox-Admin-Token": admin_token},
    )
    assert resp.status_code == 200
    assert resp.json()["webhook_endpoints_fired"] == 0
    await asyncio.sleep(0.05)
    assert captured == []
