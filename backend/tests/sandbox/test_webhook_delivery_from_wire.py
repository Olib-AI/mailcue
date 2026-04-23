"""End-to-end tests: wire-level send → webhook delivery.

For each of the five phone providers we:

1. Register a :class:`SandboxWebhookEndpoint` pointing at a capture URL.
2. Hit the real provider REST path (``POST .../Messages.json`` etc.).
3. Intercept the outbound HTTP ``POST`` the webhook worker makes and
   capture (URL, headers, body).
4. Assert the captured payload matches the provider's on-wire shape and
   carries the expected provider-specific signing header.

The interception happens by monkeypatching ``httpx.AsyncClient`` inside
``app.sandbox.webhook_worker`` — not ``app.sandbox.webhook_raw`` — so the
side paths (voice status callbacks) keep working unmodified.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, ClassVar

import pytest
from httpx import AsyncClient

from tests.conftest import basic_auth_header


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
    """Minimal stand-in for :class:`httpx.AsyncClient` used by the
    webhook worker.  Captures every outbound POST so tests can assert
    on the exact wire shape the worker emitted.
    """

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
async def captured_webhook_calls(
    _engine_and_session: Any, monkeypatch: pytest.MonkeyPatch
) -> list[CapturedRequest]:
    """Patch the worker's ``httpx.AsyncClient`` and return its capture buffer.

    Also re-points the module-level ``AsyncSessionLocal`` at the in-memory
    test factory so the background webhook-delivery task sees the same
    database rows the request-scoped session wrote.
    """
    import app.database as _db
    import app.sandbox.webhook_worker as ww

    _StubClient.calls = []
    monkeypatch.setattr(ww.httpx, "AsyncClient", _StubClient)
    _factory = _engine_and_session[1]
    monkeypatch.setattr(_db, "AsyncSessionLocal", _factory)
    return _StubClient.calls


async def _wait_for_calls(calls: list[CapturedRequest], n: int = 1) -> None:
    """Give the fire-and-forget webhook task a few event-loop turns."""
    for _ in range(80):
        if len(calls) >= n:
            return
        await asyncio.sleep(0.01)


async def _register_webhook(
    client: AsyncClient, provider_id: str, url: str, secret: str | None = None
) -> str:
    resp = await client.post(
        f"/api/v1/sandbox/providers/{provider_id}/webhooks",
        json={"url": url, "event_types": ["message.created"], "secret": secret},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── Twilio ────────────────────────────────────────────────────────────────


async def test_twilio_wire_fires_form_encoded_signed_webhook(
    client: AsyncClient,
    twilio_provider: dict,
    captured_webhook_calls: list[CapturedRequest],
) -> None:
    sid = twilio_provider["credentials"]["account_sid"]
    await _register_webhook(client, twilio_provider["id"], "https://hooks.example.com/twilio")

    # POST via the real wire path.
    send = await client.post(
        f"/sandbox/twilio/2010-04-01/Accounts/{sid}/Messages.json",
        json={"To": "+15551234567", "From": "+15559876543", "Body": "wire hook"},
        headers={
            "Authorization": basic_auth_header(sid, twilio_provider["credentials"]["auth_token"]),
        },
    )
    assert send.status_code == 200

    await _wait_for_calls(captured_webhook_calls)
    assert captured_webhook_calls, "no webhook was fired"
    cap = captured_webhook_calls[0]
    assert cap.url == "https://hooks.example.com/twilio"
    # Twilio is form-encoded.
    assert cap.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert "X-Twilio-Signature" in cap.headers
    # Decode the body and assert the shape fase's
    # ``parse_inbound_sms_webhook`` / ``parse_status_webhook`` expect.
    from urllib.parse import parse_qs

    form = {k: v[0] for k, v in parse_qs(cap.body.decode()).items()}
    assert form["From"] == "+15559876543"
    assert form["To"] == "+15551234567"
    assert form["Body"] == "wire hook"
    assert form["MessageStatus"] == "queued"
    assert form["AccountSid"] == sid
    assert form["MessageSid"].startswith("SM")
    # Verify the signature independently — URL + sorted form-params HMAC-SHA1.
    signing_base = cap.url + "".join(f"{k}{v}" for k, v in sorted(form.items()))
    expected = base64.b64encode(
        hmac.new(
            twilio_provider["credentials"]["auth_token"].encode(),
            signing_base.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()
    assert cap.headers["X-Twilio-Signature"] == expected


# ── Bandwidth ────────────────────────────────────────────────────────────


async def test_bandwidth_wire_fires_json_array_webhook(
    client: AsyncClient,
    bandwidth_provider: dict,
    captured_webhook_calls: list[CapturedRequest],
) -> None:
    acc = bandwidth_provider["credentials"]["account_id"]
    # Patch provider with Bandwidth Basic-auth callback creds so the worker
    # can attach ``Authorization: Basic ...``.
    await client.put(
        f"/api/v1/sandbox/providers/{bandwidth_provider['id']}",
        json={
            "credentials": {
                **bandwidth_provider["credentials"],
                "callback_username": "hook_user",
                "callback_password": "hook_secret",
            }
        },
    )
    await _register_webhook(
        client, bandwidth_provider["id"], "https://hooks.example.com/bandwidth"
    )
    send = await client.post(
        f"/sandbox/bandwidth/api/v2/users/{acc}/messages",
        json={
            "applicationId": "msg-app-1",
            "to": ["+15551234567"],
            "from": "+15559876543",
            "text": "bw wire",
        },
        headers={
            "Authorization": basic_auth_header(
                bandwidth_provider["credentials"]["username"],
                bandwidth_provider["credentials"]["password"],
            )
        },
    )
    assert send.status_code == 202

    await _wait_for_calls(captured_webhook_calls)
    assert captured_webhook_calls
    cap = captured_webhook_calls[0]
    assert cap.headers["Content-Type"] == "application/json"
    assert (
        cap.headers["Authorization"]
        == "Basic " + base64.b64encode(b"hook_user:hook_secret").decode()
    )
    arr = json.loads(cap.body)
    assert isinstance(arr, list)
    entry = arr[0]
    # Status-callback envelope (outbound path).
    assert entry["type"] in {"message-sent", "message-delivered"}
    assert entry["to"] == "+15551234567"
    assert entry["message"]["from"] == "+15559876543"
    assert entry["message"]["text"] == "bw wire"


# ── Vonage ────────────────────────────────────────────────────────────────


async def test_vonage_wire_fires_status_webhook(
    client: AsyncClient,
    vonage_provider: dict,
    captured_webhook_calls: list[CapturedRequest],
) -> None:
    await _register_webhook(client, vonage_provider["id"], "https://hooks.example.com/vonage")
    send = await client.post(
        "/sandbox/vonage/v1/messages",
        json={
            "message_type": "text",
            "channel": "sms",
            "to": "+15551234567",
            "from": "+15559876543",
            "text": "vonage wire",
        },
        headers={"Authorization": "Bearer test-bearer-token"},
    )
    assert send.status_code == 202
    await _wait_for_calls(captured_webhook_calls)
    assert captured_webhook_calls
    cap = captured_webhook_calls[0]
    assert cap.headers["Content-Type"] == "application/json"
    data = json.loads(cap.body)
    # Outbound Vonage status webhook: message_uuid + status + timestamp.
    assert data["status"] in {"submitted", "delivered"}
    assert "message_uuid" in data


# ── Plivo ─────────────────────────────────────────────────────────────────


async def test_plivo_wire_fires_form_encoded_signed_webhook(
    client: AsyncClient,
    plivo_provider: dict,
    captured_webhook_calls: list[CapturedRequest],
) -> None:
    auth_id = plivo_provider["credentials"]["auth_id"]
    await _register_webhook(client, plivo_provider["id"], "https://hooks.example.com/plivo")
    send = await client.post(
        f"/sandbox/plivo/v1/Account/{auth_id}/Message/",
        json={"src": "+15559876543", "dst": "+15551234567", "text": "plivo wire"},
        headers={
            "Authorization": basic_auth_header(
                auth_id, plivo_provider["credentials"]["auth_token"]
            )
        },
    )
    assert send.status_code == 202
    await _wait_for_calls(captured_webhook_calls)
    assert captured_webhook_calls
    cap = captured_webhook_calls[0]
    assert cap.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert "X-Plivo-Signature-V3" in cap.headers
    assert "X-Plivo-Signature-V3-Nonce" in cap.headers
    from app.sandbox.signers import verify_plivo_v3_signature

    assert verify_plivo_v3_signature(
        auth_token=plivo_provider["credentials"]["auth_token"],
        url=cap.url,
        body=cap.body,
        nonce=cap.headers["X-Plivo-Signature-V3-Nonce"],
        signature=cap.headers["X-Plivo-Signature-V3"],
    )
    from urllib.parse import parse_qs

    form = {k: v[0] for k, v in parse_qs(cap.body.decode()).items()}
    assert form["From"] == "+15559876543"
    assert form["To"] == "+15551234567"
    assert form["Status"] in {"queued", "delivered"}


# ── Telnyx ────────────────────────────────────────────────────────────────


async def test_telnyx_wire_fires_signed_json_webhook(
    client: AsyncClient,
    telnyx_provider: dict,
    captured_webhook_calls: list[CapturedRequest],
) -> None:
    await _register_webhook(client, telnyx_provider["id"], "https://hooks.example.com/telnyx")
    send = await client.post(
        "/sandbox/telnyx/v2/messages",
        json={
            "from": "+15559876543",
            "to": "+15551234567",
            "text": "telnyx wire",
        },
        headers={"Authorization": "Bearer KEYABCDEF1234567890"},
    )
    assert send.status_code == 200
    await _wait_for_calls(captured_webhook_calls)
    assert captured_webhook_calls
    cap = captured_webhook_calls[0]
    assert cap.headers["Content-Type"] == "application/json"
    assert "telnyx-timestamp" in cap.headers
    assert "telnyx-signature-ed25519" in cap.headers
    data = json.loads(cap.body)
    assert data["data"]["record_type"] == "event"
    assert data["data"]["event_type"] in {
        "message.sent",
        "message.finalized",
    }
    payload = data["data"]["payload"]
    assert payload["direction"] == "outbound"
    assert payload["from"]["phone_number"] == "+15559876543"
    assert payload["to"][0]["phone_number"] == "+15551234567"
    # Verify Ed25519 signature.
    from app.sandbox.providers.telnyx.service import verify_signature

    # Need the provider's public key.
    prov_resp = await client.get(f"/api/v1/sandbox/providers/{telnyx_provider['id']}")
    pub = prov_resp.json()["credentials"].get("ed25519_public_key")
    assert pub
    assert verify_signature(
        pub,
        cap.body,
        cap.headers["telnyx-timestamp"],
        cap.headers["telnyx-signature-ed25519"],
    )


# ── Idempotency guard ─────────────────────────────────────────────────────


async def test_no_webhook_fires_when_no_endpoint_registered(
    client: AsyncClient,
    twilio_provider: dict,
    captured_webhook_calls: list[CapturedRequest],
) -> None:
    """Worker early-returns silently when the provider has no endpoints."""
    sid = twilio_provider["credentials"]["account_sid"]
    send = await client.post(
        f"/sandbox/twilio/2010-04-01/Accounts/{sid}/Messages.json",
        json={"To": "+15551234567", "From": "+15559876543", "Body": "no hook"},
        headers={
            "Authorization": basic_auth_header(sid, twilio_provider["credentials"]["auth_token"])
        },
    )
    assert send.status_code == 200
    # Give any tasks time to spin.
    await asyncio.sleep(0.05)
    assert captured_webhook_calls == []
