"""End-to-end tests for the Mattermost sandbox provider.

Validates that the sandbox returns responses in the exact Mattermost API v4
format, including proper post objects and Bearer token auth.
"""

from __future__ import annotations

from httpx import AsyncClient

MM_PREFIX = "/sandbox/mattermost/api/v4"


def _auth(provider: dict) -> dict[str, str]:
    token = provider["credentials"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Auth ─────────────────────────────────────────────────────────


async def test_invalid_auth(client: AsyncClient):
    resp = await client.post(
        f"{MM_PREFIX}/posts",
        json={"channel_id": "ch1", "message": "hi"},
        headers={"Authorization": "Bearer bad-token"},
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["status_code"] == 401


async def test_missing_auth(client: AsyncClient):
    resp = await client.post(
        f"{MM_PREFIX}/posts",
        json={"channel_id": "ch1", "message": "hi"},
    )
    assert resp.status_code == 401


# ── Create post ──────────────────────────────────────────────────


async def test_create_post(client: AsyncClient, mattermost_provider: dict):
    resp = await client.post(
        f"{MM_PREFIX}/posts",
        json={"channel_id": "town-square", "message": "Hello Mattermost!"},
        headers=_auth(mattermost_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "Hello Mattermost!"
    assert "id" in data
    assert "create_at" in data
    assert data["channel_id"] == "town-square"


async def test_create_post_with_root_id(client: AsyncClient, mattermost_provider: dict):
    # Parent post
    resp1 = await client.post(
        f"{MM_PREFIX}/posts",
        json={"channel_id": "threads-ch", "message": "Parent post"},
        headers=_auth(mattermost_provider),
    )
    parent_id = resp1.json()["id"]

    # Reply
    resp2 = await client.post(
        f"{MM_PREFIX}/posts",
        json={
            "channel_id": "threads-ch",
            "message": "Reply post",
            "root_id": parent_id,
        },
        headers=_auth(mattermost_provider),
    )
    assert resp2.status_code == 200
    assert resp2.json()["message"] == "Reply post"


# ── Get post ─────────────────────────────────────────────────────


async def test_get_post(client: AsyncClient, mattermost_provider: dict):
    create_resp = await client.post(
        f"{MM_PREFIX}/posts",
        json={"channel_id": "ch1", "message": "Fetch me"},
        headers=_auth(mattermost_provider),
    )
    post_id = create_resp.json()["id"]

    resp = await client.get(
        f"{MM_PREFIX}/posts/{post_id}",
        headers=_auth(mattermost_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == post_id
    assert data["message"] == "Fetch me"


async def test_get_post_not_found(client: AsyncClient, mattermost_provider: dict):
    resp = await client.get(
        f"{MM_PREFIX}/posts/nonexistent-post-id",
        headers=_auth(mattermost_provider),
    )
    assert resp.status_code == 404


# ── Update post ──────────────────────────────────────────────────


async def test_update_post(client: AsyncClient, mattermost_provider: dict):
    create_resp = await client.post(
        f"{MM_PREFIX}/posts",
        json={"channel_id": "ch-edit", "message": "Original"},
        headers=_auth(mattermost_provider),
    )
    post_id = create_resp.json()["id"]

    resp = await client.put(
        f"{MM_PREFIX}/posts/{post_id}",
        json={"channel_id": "ch-edit", "message": "Updated"},
        headers=_auth(mattermost_provider),
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "Updated"


# ── Delete post ──────────────────────────────────────────────────


async def test_delete_post(client: AsyncClient, mattermost_provider: dict):
    create_resp = await client.post(
        f"{MM_PREFIX}/posts",
        json={"channel_id": "ch-del", "message": "Delete me"},
        headers=_auth(mattermost_provider),
    )
    post_id = create_resp.json()["id"]

    resp = await client.delete(
        f"{MM_PREFIX}/posts/{post_id}",
        headers=_auth(mattermost_provider),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "OK"


async def test_delete_post_not_found(client: AsyncClient, mattermost_provider: dict):
    resp = await client.delete(
        f"{MM_PREFIX}/posts/nonexistent",
        headers=_auth(mattermost_provider),
    )
    assert resp.status_code == 404


# ── Channels ─────────────────────────────────────────────────────


async def test_list_channels(client: AsyncClient, mattermost_provider: dict):
    # Create a channel by posting
    await client.post(
        f"{MM_PREFIX}/posts",
        json={"channel_id": "test-channel", "message": "Creating channel"},
        headers=_auth(mattermost_provider),
    )

    resp = await client.get(
        f"{MM_PREFIX}/channels",
        headers=_auth(mattermost_provider),
    )
    assert resp.status_code == 200
    channels = resp.json()
    assert isinstance(channels, list)
    assert len(channels) >= 1


async def test_get_channel(client: AsyncClient, mattermost_provider: dict):
    channel_id = "detail-channel"
    await client.post(
        f"{MM_PREFIX}/posts",
        json={"channel_id": channel_id, "message": "msg"},
        headers=_auth(mattermost_provider),
    )

    resp = await client.get(
        f"{MM_PREFIX}/channels/{channel_id}",
        headers=_auth(mattermost_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert "name" in data


async def test_get_channel_not_found(client: AsyncClient, mattermost_provider: dict):
    resp = await client.get(
        f"{MM_PREFIX}/channels/nonexistent-channel",
        headers=_auth(mattermost_provider),
    )
    assert resp.status_code == 404


# ── Channel posts ────────────────────────────────────────────────


async def test_get_channel_posts(client: AsyncClient, mattermost_provider: dict):
    channel_id = "posts-channel"
    await client.post(
        f"{MM_PREFIX}/posts",
        json={"channel_id": channel_id, "message": "Post A"},
        headers=_auth(mattermost_provider),
    )
    await client.post(
        f"{MM_PREFIX}/posts",
        json={"channel_id": channel_id, "message": "Post B"},
        headers=_auth(mattermost_provider),
    )

    resp = await client.get(
        f"{MM_PREFIX}/channels/{channel_id}/posts",
        headers=_auth(mattermost_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "order" in data
    assert "posts" in data
    assert len(data["order"]) >= 2


# ── Users ────────────────────────────────────────────────────────


async def test_get_current_user(client: AsyncClient, mattermost_provider: dict):
    resp = await client.get(
        f"{MM_PREFIX}/users/me",
        headers=_auth(mattermost_provider),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert "username" in data


# ── Messages visible in management API ───────────────────────────


async def test_messages_in_management_api(client: AsyncClient, mattermost_provider: dict):
    provider_id = mattermost_provider["id"]

    await client.post(
        f"{MM_PREFIX}/posts",
        json={"channel_id": "mgmt-ch", "message": "Tracked via MM"},
        headers=_auth(mattermost_provider),
    )

    resp = await client.get("/api/v1/sandbox/messages", params={"provider_id": provider_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(m["content"] == "Tracked via MM" for m in data["messages"])
