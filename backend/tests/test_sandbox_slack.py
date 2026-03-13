"""End-to-end tests for the Slack sandbox provider.

Validates that the sandbox returns responses in the exact Slack Web API format,
including proper ``{"ok": true, ...}`` envelopes and Bearer token auth.
"""

from __future__ import annotations

from httpx import AsyncClient

SLACK_PREFIX = "/sandbox/slack/api"


def _auth(provider: dict) -> dict[str, str]:
    token = provider["credentials"]["bot_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Auth ─────────────────────────────────────────────────────────


async def test_invalid_auth(client: AsyncClient):
    resp = await client.post(
        f"{SLACK_PREFIX}/chat.postMessage",
        json={"channel": "C123", "text": "hi"},
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "invalid_auth"


async def test_missing_auth(client: AsyncClient):
    resp = await client.post(
        f"{SLACK_PREFIX}/chat.postMessage",
        json={"channel": "C123", "text": "hi"},
    )
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "invalid_auth"


# ── chat.postMessage ─────────────────────────────────────────────


async def test_post_message(client: AsyncClient, slack_provider: dict):
    resp = await client.post(
        f"{SLACK_PREFIX}/chat.postMessage",
        json={"channel": "C-general", "text": "Hello Slack!"},
        headers=_auth(slack_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["channel"] == "C-general"
    assert "ts" in data
    assert data["message"]["text"] == "Hello Slack!"


async def test_post_message_with_thread(client: AsyncClient, slack_provider: dict):
    # First message
    resp1 = await client.post(
        f"{SLACK_PREFIX}/chat.postMessage",
        json={"channel": "C-threads", "text": "Parent"},
        headers=_auth(slack_provider),
    )
    parent_ts = resp1.json()["ts"]

    # Reply in thread
    resp2 = await client.post(
        f"{SLACK_PREFIX}/chat.postMessage",
        json={"channel": "C-threads", "text": "Reply", "thread_ts": parent_ts},
        headers=_auth(slack_provider),
    )
    assert resp2.json()["ok"] is True


# ── chat.update ──────────────────────────────────────────────────


async def test_chat_update(client: AsyncClient, slack_provider: dict):
    # Post first
    post_resp = await client.post(
        f"{SLACK_PREFIX}/chat.postMessage",
        json={"channel": "C-edits", "text": "Original"},
        headers=_auth(slack_provider),
    )
    ts = post_resp.json()["ts"]

    # Update
    resp = await client.post(
        f"{SLACK_PREFIX}/chat.update",
        json={"channel": "C-edits", "ts": ts, "text": "Updated"},
        headers=_auth(slack_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["message"]["text"] == "Updated"


# ── chat.delete ──────────────────────────────────────────────────


async def test_chat_delete(client: AsyncClient, slack_provider: dict):
    post_resp = await client.post(
        f"{SLACK_PREFIX}/chat.postMessage",
        json={"channel": "C-deletes", "text": "Doomed"},
        headers=_auth(slack_provider),
    )
    ts = post_resp.json()["ts"]

    resp = await client.post(
        f"{SLACK_PREFIX}/chat.delete",
        json={"channel": "C-deletes", "ts": ts},
        headers=_auth(slack_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["ts"] == ts


# ── conversations.list ───────────────────────────────────────────


async def test_conversations_list(client: AsyncClient, slack_provider: dict):
    # Create a conversation by posting
    await client.post(
        f"{SLACK_PREFIX}/chat.postMessage",
        json={"channel": "C-list-test", "text": "creating channel"},
        headers=_auth(slack_provider),
    )

    resp = await client.get(
        f"{SLACK_PREFIX}/conversations.list",
        headers=_auth(slack_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["channels"], list)
    assert len(data["channels"]) >= 1


# ── conversations.info ───────────────────────────────────────────


async def test_conversations_info(client: AsyncClient, slack_provider: dict):
    # Create channel
    await client.post(
        f"{SLACK_PREFIX}/chat.postMessage",
        json={"channel": "C-info-test", "text": "msg"},
        headers=_auth(slack_provider),
    )

    resp = await client.get(
        f"{SLACK_PREFIX}/conversations.info",
        params={"channel": "C-info-test"},
        headers=_auth(slack_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "channel" in data


async def test_conversations_info_not_found(client: AsyncClient, slack_provider: dict):
    resp = await client.get(
        f"{SLACK_PREFIX}/conversations.info",
        params={"channel": "C-nonexistent"},
        headers=_auth(slack_provider),
    )
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "channel_not_found"


# ── conversations.history ────────────────────────────────────────


async def test_conversations_history(client: AsyncClient, slack_provider: dict):
    channel = "C-history-test"
    await client.post(
        f"{SLACK_PREFIX}/chat.postMessage",
        json={"channel": channel, "text": "Message 1"},
        headers=_auth(slack_provider),
    )
    await client.post(
        f"{SLACK_PREFIX}/chat.postMessage",
        json={"channel": channel, "text": "Message 2"},
        headers=_auth(slack_provider),
    )

    resp = await client.get(
        f"{SLACK_PREFIX}/conversations.history",
        params={"channel": channel},
        headers=_auth(slack_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["messages"], list)
    assert len(data["messages"]) >= 2


# ── users.list / users.info ─────────────────────────────────────


async def test_users_list(client: AsyncClient, slack_provider: dict):
    resp = await client.get(
        f"{SLACK_PREFIX}/users.list",
        headers=_auth(slack_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["members"], list)
    assert len(data["members"]) >= 1
    assert data["members"][0]["is_bot"] is True


async def test_users_info(client: AsyncClient, slack_provider: dict):
    # First get the bot user id from users.list
    list_resp = await client.get(
        f"{SLACK_PREFIX}/users.list",
        headers=_auth(slack_provider),
    )
    bot_user_id = list_resp.json()["members"][0]["id"]

    resp = await client.get(
        f"{SLACK_PREFIX}/users.info",
        params={"user": bot_user_id},
        headers=_auth(slack_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["user"]["id"] == bot_user_id


async def test_users_info_not_found(client: AsyncClient, slack_provider: dict):
    resp = await client.get(
        f"{SLACK_PREFIX}/users.info",
        params={"user": "U-nonexistent"},
        headers=_auth(slack_provider),
    )
    data = resp.json()
    assert data["ok"] is False
    assert data["error"] == "user_not_found"


# ── Messages visible in management API ───────────────────────────


async def test_messages_in_management_api(client: AsyncClient, slack_provider: dict):
    provider_id = slack_provider["id"]

    await client.post(
        f"{SLACK_PREFIX}/chat.postMessage",
        json={"channel": "C-mgmt", "text": "Tracked via Slack"},
        headers=_auth(slack_provider),
    )

    resp = await client.get("/api/v1/sandbox/messages", params={"provider_id": provider_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(m["content"] == "Tracked via Slack" for m in data["messages"])
