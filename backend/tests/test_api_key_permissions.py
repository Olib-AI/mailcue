"""End-to-end enforcement tests for API-key permissions (scopes + mailboxes).

Unlike the shared ``client`` fixture (which overrides authentication),
these tests drive the real ``get_auth`` dependency by sending an
``X-API-Key`` header for keys stored in the database, so scope and
mailbox checks run for real.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import APIKey, User
from app.auth.service import api_key_prefix, generate_api_key, hash_password
from app.mailboxes.models import Mailbox

OWNER_ID = "perm-owner-id"
MB_A = "a@mailcue.local"
MB_B = "b@mailcue.local"


async def _make_key(
    session: AsyncSession,
    *,
    scopes: list[str],
    allowed_mailboxes: list[str] | None = None,
) -> str:
    """Persist an API key and return its raw value for the X-API-Key header."""
    raw = generate_api_key()
    session.add(
        APIKey(
            user_id=OWNER_ID,
            key_hash=hash_password(raw),
            name="test-key",
            prefix=api_key_prefix(raw),
            scopes=scopes,
            allowed_mailboxes=allowed_mailboxes,
        )
    )
    await session.commit()
    return raw


@pytest.fixture()
async def perm_client(_engine_and_session: Any) -> AsyncIterator[tuple[AsyncClient, Any]]:
    """Client with real auth; yields (client, session_factory).

    Seeds an owner user and two mailboxes (A, B). Only ``get_db`` is
    overridden -- authentication runs for real off the X-API-Key header.
    """
    _engine, factory = _engine_and_session

    from app.database import get_db
    from app.main import app

    async with factory() as session:
        session.add(
            User(
                id=OWNER_ID,
                username="permowner",
                email=MB_A,
                hashed_password="unused",
                is_admin=True,
                is_active=True,
            )
        )
        for addr in (MB_A, MB_B):
            session.add(
                Mailbox(
                    address=addr,
                    domain="mailcue.local",
                    user_id=OWNER_ID,
                )
            )
        await session.commit()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac, factory
    app.dependency_overrides.clear()


# ── Scope enforcement ────────────────────────────────────────────


async def test_missing_credentials_rejected(perm_client) -> None:
    client, _ = perm_client
    resp = await client.get("/api/v1/emails", params={"mailbox": MB_A})
    assert resp.status_code == 401


async def test_invalid_key_rejected(perm_client) -> None:
    client, _ = perm_client
    resp = await client.get(
        "/api/v1/emails", params={"mailbox": MB_A}, headers={"X-API-Key": "mc_bogus"}
    )
    assert resp.status_code == 401


async def test_send_scope_required_to_send(perm_client) -> None:
    client, factory = perm_client
    async with factory() as s:
        key = await _make_key(s, scopes=["email:read"])
    resp = await client.post(
        "/api/v1/emails/send",
        headers={"X-API-Key": key},
        json={"from_address": MB_A, "to": ["x@y.com"], "subject": "hi", "text": "yo"},
    )
    assert resp.status_code == 403
    assert "email:send" in resp.json()["detail"]


async def test_delete_scope_required_to_delete(perm_client) -> None:
    client, factory = perm_client
    async with factory() as s:
        key = await _make_key(s, scopes=["email:read"])
    resp = await client.delete(
        "/api/v1/emails/1", params={"mailbox": MB_A}, headers={"X-API-Key": key}
    )
    assert resp.status_code == 403


async def test_read_scope_passes_permission_gate(perm_client, monkeypatch) -> None:
    """A key with email:read clears the scope+mailbox gate (service is stubbed)."""
    client, factory = perm_client

    async def _fake_list(**_kwargs):
        from app.emails.schemas import EmailListResponse

        return EmailListResponse(emails=[], total=0, page=1, page_size=50)

    monkeypatch.setattr("app.emails.router.list_emails", _fake_list)

    async with factory() as s:
        key = await _make_key(s, scopes=["email:read"])
    resp = await client.get("/api/v1/emails", params={"mailbox": MB_A}, headers={"X-API-Key": key})
    assert resp.status_code == 200


async def test_legacy_wildcard_key_has_full_access(perm_client, monkeypatch) -> None:
    """Keys backfilled with ['*'] keep unrestricted behaviour."""
    client, factory = perm_client

    async def _fake_list(**_kwargs):
        from app.emails.schemas import EmailListResponse

        return EmailListResponse(emails=[], total=0, page=1, page_size=50)

    monkeypatch.setattr("app.emails.router.list_emails", _fake_list)

    async with factory() as s:
        key = await _make_key(s, scopes=["*"])
    resp = await client.get("/api/v1/emails", params={"mailbox": MB_A}, headers={"X-API-Key": key})
    assert resp.status_code == 200


# ── Mailbox allow-list enforcement ───────────────────────────────


async def test_mailbox_allow_list_blocks_other_mailbox(perm_client) -> None:
    client, factory = perm_client
    async with factory() as s:
        key = await _make_key(s, scopes=["*"], allowed_mailboxes=[MB_A])
    # B is owned by the same user but not in the key's allow-list.
    resp = await client.get("/api/v1/emails", params={"mailbox": MB_B}, headers={"X-API-Key": key})
    assert resp.status_code == 403


async def test_mailbox_allow_list_filters_listing(perm_client) -> None:
    client, factory = perm_client
    async with factory() as s:
        key = await _make_key(s, scopes=["*"], allowed_mailboxes=[MB_A])
    resp = await client.get("/api/v1/mailboxes", headers={"X-API-Key": key})
    assert resp.status_code == 200
    addrs = {m["address"] for m in resp.json()["mailboxes"]}
    assert addrs == {MB_A}


# ── API-key self-management + privilege escalation ───────────────


async def test_key_without_apikey_read_cannot_list(perm_client) -> None:
    client, factory = perm_client
    async with factory() as s:
        key = await _make_key(s, scopes=["email:read"])
    resp = await client.get("/api/v1/auth/api-keys", headers={"X-API-Key": key})
    assert resp.status_code == 403


async def test_key_cannot_create_broader_key(perm_client) -> None:
    """A scoped key with apikey:manage cannot mint a more powerful key."""
    client, factory = perm_client
    async with factory() as s:
        key = await _make_key(s, scopes=["email:read", "apikey:manage"])
    resp = await client.post(
        "/api/v1/auth/api-keys",
        headers={"X-API-Key": key},
        json={"name": "escalated", "scopes": ["*"]},
    )
    assert resp.status_code == 403


async def test_key_can_create_narrower_key(perm_client) -> None:
    client, factory = perm_client
    async with factory() as s:
        key = await _make_key(s, scopes=["email:read", "email:send", "apikey:manage"])
    resp = await client.post(
        "/api/v1/auth/api-keys",
        headers={"X-API-Key": key},
        json={"name": "narrow", "scopes": ["email:read"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["scopes"] == ["email:read"]
    assert body["key"].startswith("mc_")


async def test_create_key_rejects_unknown_scope(perm_client) -> None:
    client, factory = perm_client
    async with factory() as s:
        key = await _make_key(s, scopes=["*"])
    resp = await client.post(
        "/api/v1/auth/api-keys",
        headers={"X-API-Key": key},
        json={"name": "bad", "scopes": ["email:bogus"]},
    )
    assert resp.status_code == 400


async def test_create_key_rejects_unowned_mailbox(perm_client) -> None:
    client, factory = perm_client
    async with factory() as s:
        key = await _make_key(s, scopes=["*"])
    resp = await client.post(
        "/api/v1/auth/api-keys",
        headers={"X-API-Key": key},
        json={"name": "x", "allowed_mailboxes": ["stranger@elsewhere.com"]},
    )
    assert resp.status_code == 400


async def test_scope_catalog_lists_scopes(perm_client) -> None:
    client, factory = perm_client
    async with factory() as s:
        key = await _make_key(s, scopes=["*"])
    resp = await client.get("/api/v1/auth/api-keys/scopes", headers={"X-API-Key": key})
    assert resp.status_code == 200
    values = {s["value"] for s in resp.json()["scopes"]}
    assert {"email:read", "email:send", "email:delete", "mailbox:read"} <= values
