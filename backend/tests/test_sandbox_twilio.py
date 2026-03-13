"""End-to-end tests for the Twilio sandbox provider.

Validates that the sandbox returns responses in the exact Twilio REST API
format, including proper SID fields, HTTP Basic auth, and JSON envelopes.
"""

from __future__ import annotations

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


# ── Auth ─────────────────────────────────────────────────────────


async def test_invalid_auth(client: AsyncClient, twilio_provider: dict):
    sid = twilio_provider["credentials"]["account_sid"]
    resp = await client.post(
        f"{TWILIO_PREFIX}/{sid}/Messages.json",
        json={"To": "+1234567890", "From": "+0987654321", "Body": "hi"},
        headers={"Authorization": basic_auth_header(sid, "wrong-token")},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["code"] == 20003


async def test_missing_auth(client: AsyncClient, twilio_provider: dict):
    sid = twilio_provider["credentials"]["account_sid"]
    resp = await client.post(
        f"{TWILIO_PREFIX}/{sid}/Messages.json",
        json={"To": "+1234567890", "From": "+0987654321", "Body": "hi"},
    )
    assert resp.status_code == 401


async def test_mismatched_sid_in_url(client: AsyncClient, twilio_provider: dict):
    """The account_sid in the URL must match the Basic auth username."""
    token = twilio_provider["credentials"]["auth_token"]
    resp = await client.post(
        f"{TWILIO_PREFIX}/AC-wrong-sid/Messages.json",
        json={"To": "+1234567890", "From": "+0987654321", "Body": "hi"},
        headers={"Authorization": basic_auth_header("AC-wrong-sid", token)},
    )
    assert resp.status_code == 401


# ── Send SMS ─────────────────────────────────────────────────────


async def test_send_sms(client: AsyncClient, twilio_provider: dict):
    resp = await client.post(
        _url(twilio_provider, "/Messages.json"),
        json={
            "To": "+15551234567",
            "From": "+15559876543",
            "Body": "Hello from Twilio sandbox!",
        },
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "sid" in data
    assert data["sid"].startswith("SM")
    assert data["body"] == "Hello from Twilio sandbox!"
    assert data["status"] in ("queued", "sent")
    assert data["to"] == "+15551234567"
    assert "date_created" in data


async def test_send_sms_with_status_callback(client: AsyncClient, twilio_provider: dict):
    resp = await client.post(
        _url(twilio_provider, "/Messages.json"),
        json={
            "To": "+15551111111",
            "From": "+15552222222",
            "Body": "Callback test",
            "StatusCallback": "https://example.com/status",
        },
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 200
    assert resp.json()["sid"].startswith("SM")


# ── List messages ────────────────────────────────────────────────


async def test_list_messages(client: AsyncClient, twilio_provider: dict):
    # Send a few messages first
    for i in range(3):
        await client.post(
            _url(twilio_provider, "/Messages.json"),
            json={
                "To": f"+1555000{i:04d}",
                "From": "+15559999999",
                "Body": f"Message {i}",
            },
            headers=_auth(twilio_provider),
        )

    resp = await client.get(
        _url(twilio_provider, "/Messages.json"),
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    assert isinstance(data["messages"], list)
    assert len(data["messages"]) >= 3
    # Twilio list envelope fields
    assert "uri" in data
    assert "page" in data


# ── Get single message ───────────────────────────────────────────


async def test_get_message(client: AsyncClient, twilio_provider: dict):
    # Send a message
    send_resp = await client.post(
        _url(twilio_provider, "/Messages.json"),
        json={
            "To": "+15553334444",
            "From": "+15555556666",
            "Body": "Fetchable message",
        },
        headers=_auth(twilio_provider),
    )
    msg_sid = send_resp.json()["sid"]

    # Fetch it
    resp = await client.get(
        _url(twilio_provider, f"/Messages/{msg_sid}.json"),
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sid"] == msg_sid
    assert data["body"] == "Fetchable message"


async def test_get_message_not_found(client: AsyncClient, twilio_provider: dict):
    resp = await client.get(
        _url(twilio_provider, "/Messages/SM-nonexistent.json"),
        headers=_auth(twilio_provider),
    )
    assert resp.status_code == 404
    data = resp.json()
    assert data["code"] == 20404


# ── Messages visible in management API ───────────────────────────


async def test_messages_in_management_api(client: AsyncClient, twilio_provider: dict):
    provider_id = twilio_provider["id"]

    await client.post(
        _url(twilio_provider, "/Messages.json"),
        json={
            "To": "+15557777777",
            "From": "+15558888888",
            "Body": "Tracked via Twilio",
        },
        headers=_auth(twilio_provider),
    )

    resp = await client.get("/api/v1/sandbox/messages", params={"provider_id": provider_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(m["content"] == "Tracked via Twilio" for m in data["messages"])


# ── Conversations created automatically ──────────────────────────


async def test_conversation_created(client: AsyncClient, twilio_provider: dict):
    provider_id = twilio_provider["id"]

    await client.post(
        _url(twilio_provider, "/Messages.json"),
        json={
            "To": "+15550001111",
            "From": "+15550002222",
            "Body": "Conversation test",
        },
        headers=_auth(twilio_provider),
    )

    resp = await client.get(f"/api/v1/sandbox/providers/{provider_id}/conversations")
    assert resp.status_code == 200
    convs = resp.json()
    assert len(convs) >= 1
    # Twilio conversation external_id is "from->to"
    assert any("+15550002222->+15550001111" in c["external_id"] for c in convs)
