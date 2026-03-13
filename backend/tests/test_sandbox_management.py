"""End-to-end tests for the sandbox management API.

Tests the CRUD operations for providers, conversations, messages,
webhook endpoints, and the simulate inbound feature.
"""

from __future__ import annotations

from httpx import AsyncClient

# ── Provider CRUD ────────────────────────────────────────────────


async def test_create_provider(client: AsyncClient):
    resp = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "telegram",
            "name": "My Bot",
            "credentials": {"bot_token": "tok1"},
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["provider_type"] == "telegram"
    assert data["name"] == "My Bot"
    assert data["is_active"] is True
    assert "id" in data


async def test_list_providers(client: AsyncClient):
    await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "slack",
            "name": "Slack A",
            "credentials": {"bot_token": "xoxb-a"},
        },
    )
    resp = await client.get("/api/v1/sandbox/providers")
    assert resp.status_code == 200
    providers = resp.json()
    assert isinstance(providers, list)
    assert len(providers) >= 1


async def test_get_provider(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "telegram",
            "name": "Get Test",
            "credentials": {"bot_token": "tok-get"},
        },
    )
    pid = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/sandbox/providers/{pid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == pid
    assert data["name"] == "Get Test"
    # Should include sandbox_url hint
    assert "sandbox_url" in data


async def test_get_provider_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/sandbox/providers/nonexistent-id")
    assert resp.status_code == 404


async def test_update_provider(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "mattermost",
            "name": "Original",
            "credentials": {"access_token": "mm-tok"},
        },
    )
    pid = create_resp.json()["id"]

    resp = await client.put(
        f"/api/v1/sandbox/providers/{pid}",
        json={"name": "Renamed", "is_active": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Renamed"
    assert data["is_active"] is False
    assert data["updated_at"] is not None


async def test_delete_provider(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "twilio",
            "name": "Deletable",
            "credentials": {"account_sid": "ACdel", "auth_token": "del-tok"},
        },
    )
    pid = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/sandbox/providers/{pid}")
    assert resp.status_code == 204

    # Verify it's gone
    resp = await client.get(f"/api/v1/sandbox/providers/{pid}")
    assert resp.status_code == 404


# ── Simulate inbound ─────────────────────────────────────────────


async def test_simulate_inbound(client: AsyncClient, telegram_provider: dict):
    pid = telegram_provider["id"]

    resp = await client.post(
        f"/api/v1/sandbox/providers/{pid}/simulate",
        json={
            "sender": "Alice",
            "content": "Hey there!",
            "conversation_name": "Alice Chat",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["direction"] == "inbound"
    assert data["sender"] == "Alice"
    assert data["content"] == "Hey there!"


async def test_simulate_creates_conversation(client: AsyncClient, telegram_provider: dict):
    pid = telegram_provider["id"]

    await client.post(
        f"/api/v1/sandbox/providers/{pid}/simulate",
        json={"sender": "Bob", "content": "New convo"},
    )

    resp = await client.get(f"/api/v1/sandbox/providers/{pid}/conversations")
    assert resp.status_code == 200
    convs = resp.json()
    assert any("Bob" in (c.get("name") or "") for c in convs)


async def test_simulate_provider_not_found(client: AsyncClient):
    resp = await client.post(
        "/api/v1/sandbox/providers/nonexistent/simulate",
        json={"sender": "X", "content": "Y"},
    )
    assert resp.status_code == 404


# ── Conversations ────────────────────────────────────────────────


async def test_list_conversations(client: AsyncClient, telegram_provider: dict):
    pid = telegram_provider["id"]
    token = telegram_provider["credentials"]["bot_token"]

    # Send a message to create a conversation
    await client.post(
        f"/sandbox/telegram/bot{token}/sendMessage",
        json={"chat_id": 777, "text": "Creating conv"},
    )

    resp = await client.get(f"/api/v1/sandbox/providers/{pid}/conversations")
    assert resp.status_code == 200
    convs = resp.json()
    assert len(convs) >= 1
    assert "id" in convs[0]
    assert "external_id" in convs[0]


# ── Messages ─────────────────────────────────────────────────────


async def test_list_messages_for_conversation(client: AsyncClient, telegram_provider: dict):
    pid = telegram_provider["id"]
    token = telegram_provider["credentials"]["bot_token"]

    # Send to create conversation + message
    await client.post(
        f"/sandbox/telegram/bot{token}/sendMessage",
        json={"chat_id": 888, "text": "Conv msg"},
    )

    # Get conversations
    convs_resp = await client.get(f"/api/v1/sandbox/providers/{pid}/conversations")
    convs = convs_resp.json()
    conv = next(c for c in convs if c["external_id"] == "888")

    resp = await client.get(f"/api/v1/sandbox/providers/{pid}/conversations/{conv['id']}/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(m["content"] == "Conv msg" for m in data["messages"])


async def test_list_messages_cross_provider(client: AsyncClient):
    # Create two providers of different types
    r1 = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "telegram",
            "name": "Cross T",
            "credentials": {"bot_token": "cross-t"},
        },
    )
    r2 = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "slack",
            "name": "Cross S",
            "credentials": {"bot_token": "cross-s"},
        },
    )
    pid1 = r1.json()["id"]
    pid2 = r2.json()["id"]

    # Simulate inbound on each
    await client.post(
        f"/api/v1/sandbox/providers/{pid1}/simulate",
        json={"sender": "T-User", "content": "From telegram"},
    )
    await client.post(
        f"/api/v1/sandbox/providers/{pid2}/simulate",
        json={"sender": "S-User", "content": "From slack"},
    )

    # Cross-provider query (no provider_id filter)
    resp = await client.get("/api/v1/sandbox/messages")
    assert resp.status_code == 200
    data = resp.json()
    contents = [m["content"] for m in data["messages"]]
    assert "From telegram" in contents
    assert "From slack" in contents


# ── Webhook endpoints ────────────────────────────────────────────


async def test_webhook_crud(client: AsyncClient, telegram_provider: dict):
    pid = telegram_provider["id"]

    # Create
    create_resp = await client.post(
        f"/api/v1/sandbox/providers/{pid}/webhooks",
        json={"url": "https://example.com/wh", "event_types": ["message.created"]},
    )
    assert create_resp.status_code == 201
    wh = create_resp.json()
    assert wh["url"] == "https://example.com/wh"
    wh_id = wh["id"]

    # List
    list_resp = await client.get(f"/api/v1/sandbox/providers/{pid}/webhooks")
    assert list_resp.status_code == 200
    webhooks = list_resp.json()
    assert any(w["id"] == wh_id for w in webhooks)

    # Delete
    del_resp = await client.delete(f"/api/v1/sandbox/webhooks/{wh_id}")
    assert del_resp.status_code == 204

    # Verify gone
    list_resp2 = await client.get(f"/api/v1/sandbox/providers/{pid}/webhooks")
    assert not any(w["id"] == wh_id for w in list_resp2.json())


async def test_delete_webhook_not_found(client: AsyncClient):
    resp = await client.delete("/api/v1/sandbox/webhooks/nonexistent")
    assert resp.status_code == 404


# ── Webhook deliveries ───────────────────────────────────────────


async def test_list_webhook_deliveries(client: AsyncClient, telegram_provider: dict):
    pid = telegram_provider["id"]
    resp = await client.get(f"/api/v1/sandbox/providers/{pid}/webhook-deliveries")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
