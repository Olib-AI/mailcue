"""End-to-end tests for the Telegram sandbox provider.

Each test exercises the full request path: HTTP request -> FastAPI router ->
service layer -> SQLite database, validating that the sandbox returns
responses in the exact Telegram Bot API format.
"""

from __future__ import annotations

from httpx import AsyncClient

# ── getMe ────────────────────────────────────────────────────────


async def test_get_me_returns_bot_info(client: AsyncClient, telegram_provider: dict):
    token = telegram_provider["credentials"]["bot_token"]
    resp = await client.post(f"/sandbox/telegram/bot{token}/getMe")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    result = data["result"]
    assert result["is_bot"] is True
    assert result["first_name"] == telegram_provider["name"]


async def test_get_me_invalid_token(client: AsyncClient):
    resp = await client.post("/sandbox/telegram/botINVALID_TOKEN/getMe")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == 401


# ── sendMessage ──────────────────────────────────────────────────


async def test_send_message(client: AsyncClient, telegram_provider: dict):
    token = telegram_provider["credentials"]["bot_token"]
    resp = await client.post(
        f"/sandbox/telegram/bot{token}/sendMessage",
        json={"chat_id": 12345, "text": "Hello from test!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    result = data["result"]
    assert result["text"] == "Hello from test!"
    assert result["chat"]["id"] is not None
    assert "message_id" in result
    assert "date" in result
    assert result["from"]["is_bot"] is True


async def test_send_message_creates_conversation(client: AsyncClient, telegram_provider: dict):
    token = telegram_provider["credentials"]["bot_token"]
    provider_id = telegram_provider["id"]

    await client.post(
        f"/sandbox/telegram/bot{token}/sendMessage",
        json={"chat_id": 99999, "text": "convo test"},
    )

    # Verify conversation was created via management API
    resp = await client.get(f"/api/v1/sandbox/providers/{provider_id}/conversations")
    assert resp.status_code == 200
    convs = resp.json()
    assert any(c["external_id"] == "99999" for c in convs)


# ── sendPhoto ────────────────────────────────────────────────────


async def test_send_photo(client: AsyncClient, telegram_provider: dict):
    token = telegram_provider["credentials"]["bot_token"]
    resp = await client.post(
        f"/sandbox/telegram/bot{token}/sendPhoto",
        data={"chat_id": "12345", "caption": "A nice photo"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


# ── sendDocument ─────────────────────────────────────────────────


async def test_send_document(client: AsyncClient, telegram_provider: dict):
    token = telegram_provider["credentials"]["bot_token"]
    resp = await client.post(
        f"/sandbox/telegram/bot{token}/sendDocument",
        data={"chat_id": "12345", "caption": "Important doc"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


# ── editMessageText ──────────────────────────────────────────────


async def test_edit_message_text(client: AsyncClient, telegram_provider: dict):
    token = telegram_provider["credentials"]["bot_token"]

    # Send first
    send_resp = await client.post(
        f"/sandbox/telegram/bot{token}/sendMessage",
        json={"chat_id": 12345, "text": "Original"},
    )
    msg_id = send_resp.json()["result"]["message_id"]

    # Edit
    resp = await client.post(
        f"/sandbox/telegram/bot{token}/editMessageText",
        json={"chat_id": 12345, "message_id": msg_id, "text": "Edited text"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["result"]["text"] == "Edited text"


# ── deleteMessage ────────────────────────────────────────────────


async def test_delete_message(client: AsyncClient, telegram_provider: dict):
    token = telegram_provider["credentials"]["bot_token"]

    send_resp = await client.post(
        f"/sandbox/telegram/bot{token}/sendMessage",
        json={"chat_id": 12345, "text": "To be deleted"},
    )
    msg_id = send_resp.json()["result"]["message_id"]

    resp = await client.post(
        f"/sandbox/telegram/bot{token}/deleteMessage",
        json={"chat_id": 12345, "message_id": msg_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["result"] is True


# ── Webhook management ───────────────────────────────────────────


async def test_set_and_get_webhook(client: AsyncClient, telegram_provider: dict):
    token = telegram_provider["credentials"]["bot_token"]

    # Set webhook
    resp = await client.post(
        f"/sandbox/telegram/bot{token}/setWebhook",
        json={"url": "https://example.com/hook"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "Webhook was set" in data["description"]

    # Get webhook info
    resp = await client.post(f"/sandbox/telegram/bot{token}/getWebhookInfo")
    data = resp.json()
    assert data["ok"] is True
    assert data["result"]["url"] == "https://example.com/hook"


async def test_delete_webhook(client: AsyncClient, telegram_provider: dict):
    token = telegram_provider["credentials"]["bot_token"]

    # Set then delete
    await client.post(
        f"/sandbox/telegram/bot{token}/setWebhook",
        json={"url": "https://example.com/hook"},
    )
    resp = await client.post(f"/sandbox/telegram/bot{token}/deleteWebhook")
    assert resp.json()["ok"] is True

    # Verify it's gone
    info = await client.post(f"/sandbox/telegram/bot{token}/getWebhookInfo")
    assert info.json()["result"]["url"] == ""


# ── getUpdates ───────────────────────────────────────────────────


async def test_get_updates_returns_inbound(client: AsyncClient, telegram_provider: dict):
    token = telegram_provider["credentials"]["bot_token"]
    provider_id = telegram_provider["id"]

    # Simulate an inbound message via management API
    sim_resp = await client.post(
        f"/api/v1/sandbox/providers/{provider_id}/simulate",
        json={"sender": "TestUser", "content": "Hello bot!"},
    )
    assert sim_resp.status_code == 201

    # Poll for updates
    resp = await client.post(
        f"/sandbox/telegram/bot{token}/getUpdates",
        json={"limit": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    updates = data["result"]
    assert isinstance(updates, list)
    assert len(updates) >= 1

    # Validate update structure
    update = updates[-1]
    assert "update_id" in update
    assert "message" in update
    assert update["message"]["text"] == "Hello bot!"


# ── Messages visible in management API ───────────────────────────


async def test_messages_visible_in_management_api(client: AsyncClient, telegram_provider: dict):
    token = telegram_provider["credentials"]["bot_token"]
    provider_id = telegram_provider["id"]

    await client.post(
        f"/sandbox/telegram/bot{token}/sendMessage",
        json={"chat_id": 42, "text": "Tracked message"},
    )

    resp = await client.get("/api/v1/sandbox/messages", params={"provider_id": provider_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(m["content"] == "Tracked message" for m in data["messages"])
