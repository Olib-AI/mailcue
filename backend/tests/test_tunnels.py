"""End-to-end tests for the SMTP tunnels module.

Covers:
  - Admin CRUD round-trip and 403 for non-admins.
  - Validation rejects malformed pubkey / port / name.
  - ``tunnels.json`` is rendered correctly after every mutation.
  - Graceful-degradation when the configured path is unwritable.
  - Health-check against an open and a closed TCP port.
  - Client-identity GET/PUT semantics.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import socket
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# 32 bytes of zeros encoded as base64 -- shape-valid X25519 public key.
_VALID_PUBKEY_B64: str = base64.b64encode(b"\x00" * 32).decode()
_VALID_PUBKEY_B64_ALT: str = base64.b64encode(b"\x01" * 32).decode()


def _override_settings_path(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """Point ``settings.tunnels_config_path`` at *target* for the duration of the test."""
    from app.config import settings

    monkeypatch.setattr(settings, "tunnels_config_path", str(target), raising=False)


# ── Validation ────────────────────────────────────────────────────


async def test_create_tunnel_rejects_short_pubkey(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _override_settings_path(monkeypatch, tmp_path / "tunnels.json")

    bad_pubkey = base64.b64encode(b"\x00" * 31).decode()
    resp = await client.post(
        "/api/v1/tunnels",
        json={
            "name": "edge-1",
            "endpoint_host": "1.2.3.4",
            "endpoint_port": 7843,
            "server_pubkey": bad_pubkey,
        },
    )
    assert resp.status_code == 422


async def test_create_tunnel_rejects_bad_port(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _override_settings_path(monkeypatch, tmp_path / "tunnels.json")

    resp = await client.post(
        "/api/v1/tunnels",
        json={
            "name": "edge-port",
            "endpoint_host": "1.2.3.4",
            "endpoint_port": 70000,
            "server_pubkey": _VALID_PUBKEY_B64,
        },
    )
    assert resp.status_code == 422


async def test_create_tunnel_rejects_invalid_name(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _override_settings_path(monkeypatch, tmp_path / "tunnels.json")

    resp = await client.post(
        "/api/v1/tunnels",
        json={
            "name": "edge 1!",  # space + bang are not allowed
            "endpoint_host": "1.2.3.4",
            "endpoint_port": 7843,
            "server_pubkey": _VALID_PUBKEY_B64,
        },
    )
    assert resp.status_code == 422


# ── CRUD round-trip + tunnels.json shape ─────────────────────────


async def test_full_crud_and_tunnels_json(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    json_path = tmp_path / "tunnels.json"
    _override_settings_path(monkeypatch, json_path)

    # Create -- written file should reflect a single tunnel.
    create_resp = await client.post(
        "/api/v1/tunnels",
        json={
            "name": "edge-paris",
            "endpoint_host": "edge.example.com",
            "endpoint_port": 7843,
            "server_pubkey": _VALID_PUBKEY_B64,
            "weight": 5,
            "notes": "primary EU edge",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    tunnel = create_resp.json()
    assert tunnel["name"] == "edge-paris"
    assert tunnel["weight"] == 5
    assert tunnel["enabled"] is True
    tunnel_id: str = tunnel["id"]

    assert json_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["version"] == 1
    assert payload["selection"] == "round_robin"
    assert payload["client_static_key_path"] == "/var/lib/mailcue-sidecar/client.key"
    assert len(payload["tunnels"]) == 1
    entry = payload["tunnels"][0]
    assert entry == {
        "id": tunnel_id,
        "name": "edge-paris",
        "endpoint": "edge.example.com:7843",
        "server_pubkey": _VALID_PUBKEY_B64,
        "enabled": True,
        "weight": 5,
    }

    # List
    list_resp = await client.get("/api/v1/tunnels")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    # Detail
    get_resp = await client.get(f"/api/v1/tunnels/{tunnel_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "edge-paris"

    # Update -- weight + endpoint should be reflected on disk.
    patch_resp = await client.patch(
        f"/api/v1/tunnels/{tunnel_id}",
        json={"weight": 10, "endpoint_host": "new.example.com", "endpoint_port": 7844},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["weight"] == 10

    payload2 = json.loads(json_path.read_text())
    assert payload2["tunnels"][0]["endpoint"] == "new.example.com:7844"
    assert payload2["tunnels"][0]["weight"] == 10

    # Add a second tunnel and confirm sort-by-name.
    create_resp2 = await client.post(
        "/api/v1/tunnels",
        json={
            "name": "alpha-edge",
            "endpoint_host": "alpha.example.com",
            "endpoint_port": 7843,
            "server_pubkey": _VALID_PUBKEY_B64_ALT,
        },
    )
    assert create_resp2.status_code == 201

    payload3 = json.loads(json_path.read_text())
    names = [t["name"] for t in payload3["tunnels"]]
    assert names == sorted(names) == ["alpha-edge", "edge-paris"]

    # Delete
    del_resp = await client.delete(f"/api/v1/tunnels/{tunnel_id}")
    assert del_resp.status_code == 204
    payload4 = json.loads(json_path.read_text())
    assert [t["name"] for t in payload4["tunnels"]] == ["alpha-edge"]


# ── Conflict on duplicate name ───────────────────────────────────


async def test_create_tunnel_conflict_on_duplicate_name(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _override_settings_path(monkeypatch, tmp_path / "tunnels.json")

    body = {
        "name": "dup-edge",
        "endpoint_host": "1.2.3.4",
        "endpoint_port": 7843,
        "server_pubkey": _VALID_PUBKEY_B64,
    }
    first = await client.post("/api/v1/tunnels", json=body)
    assert first.status_code == 201
    second = await client.post("/api/v1/tunnels", json=body)
    assert second.status_code == 409


# ── Graceful degradation ─────────────────────────────────────────


async def test_tunnels_json_graceful_degradation(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the configured path's parent does not exist, the API still succeeds."""
    bogus_path = "/proc/1/no-write/tunnels.json"
    monkeypatch.setattr(
        "app.config.settings.tunnels_config_path",
        bogus_path,
        raising=False,
    )

    create_resp = await client.post(
        "/api/v1/tunnels",
        json={
            "name": "no-disk-edge",
            "endpoint_host": "1.2.3.4",
            "endpoint_port": 7843,
            "server_pubkey": _VALID_PUBKEY_B64,
        },
    )
    assert create_resp.status_code == 201, create_resp.text

    # Tunnel must still appear in DB-driven listing.
    list_resp = await client.get("/api/v1/tunnels")
    assert list_resp.status_code == 200
    names = [t["name"] for t in list_resp.json()]
    assert "no-disk-edge" in names

    # The reload helper must report ``written=False`` with a reason.
    reload_resp = await client.post("/api/v1/tunnels/reload-config")
    assert reload_resp.status_code == 200
    body = reload_resp.json()
    assert body["written"] is False
    assert body["reason"]


# ── Health check ─────────────────────────────────────────────────


async def test_health_check_open_and_closed_ports(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _override_settings_path(monkeypatch, tmp_path / "tunnels.json")

    # Bind a listener on a free local port -- echoes are unnecessary; a
    # plain ``listen()`` is enough for ``asyncio.open_connection`` to win.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    open_port: int = listener.getsockname()[1]

    try:
        create_open = await client.post(
            "/api/v1/tunnels",
            json={
                "name": "open-edge",
                "endpoint_host": "127.0.0.1",
                "endpoint_port": open_port,
                "server_pubkey": _VALID_PUBKEY_B64,
            },
        )
        assert create_open.status_code == 201
        open_id = create_open.json()["id"]

        check_open = await client.post(f"/api/v1/tunnels/{open_id}/check")
        assert check_open.status_code == 200
        assert check_open.json()["ok"] is True

    finally:
        listener.close()

    # Probe the port we just released -- should now refuse.
    create_closed = await client.post(
        "/api/v1/tunnels",
        json={
            "name": "closed-edge",
            "endpoint_host": "127.0.0.1",
            "endpoint_port": open_port,
            "server_pubkey": _VALID_PUBKEY_B64_ALT,
        },
    )
    assert create_closed.status_code == 201
    closed_id = create_closed.json()["id"]

    # Give the kernel a beat to release the port (some platforms take a tick).
    await asyncio.sleep(0.05)

    check_closed = await client.post(f"/api/v1/tunnels/{closed_id}/check")
    assert check_closed.status_code == 200
    assert check_closed.json()["ok"] is False
    assert check_closed.json()["message"]


# ── Client identity ──────────────────────────────────────────────


async def test_client_identity_get_returns_nulls_initially(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _override_settings_path(monkeypatch, tmp_path / "tunnels.json")

    resp = await client.get("/api/v1/tunnels/client-identity")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"public_key": None, "fingerprint": None, "updated_at": None}


async def test_client_identity_put_validates_and_returns_fingerprint(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _override_settings_path(monkeypatch, tmp_path / "tunnels.json")

    # Reject a 31-byte payload.
    bad = await client.put(
        "/api/v1/tunnels/client-identity",
        json={"public_key": base64.b64encode(b"\x00" * 31).decode()},
    )
    assert bad.status_code == 422

    # Accept a 32-byte payload and return the fingerprint we expect.
    raw = b"\x42" * 32
    pk = base64.b64encode(raw).decode()
    expected_fp = hashlib.sha256(raw).hexdigest()[:32]

    resp = await client.put(
        "/api/v1/tunnels/client-identity",
        json={"public_key": pk},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["public_key"] == pk
    assert body["fingerprint"] == expected_fp
    assert body["updated_at"] is not None


# ── Authorization (non-admin gets 403) ───────────────────────────


@pytest.fixture()
async def non_admin_client(_engine_and_session: Any) -> AsyncIterator[AsyncClient]:
    """A second client whose user is *not* an admin."""
    _engine, factory = _engine_and_session

    from app.auth.models import User
    from app.dependencies import get_current_user
    from app.main import app

    plain_user = User(
        id="plain-user-id",
        username="plainuser",
        email="plainuser@mailcue.local",
        hashed_password="unused",
        is_admin=False,
        is_active=True,
    )
    async with factory() as session:
        session.add(plain_user)
        await session.commit()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    async def _override_get_current_user() -> User:
        return plain_user

    from app.database import get_db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


async def test_non_admin_cannot_list_tunnels(
    non_admin_client: AsyncClient,
) -> None:
    resp = await non_admin_client.get("/api/v1/tunnels")
    assert resp.status_code == 403


async def test_non_admin_cannot_create_tunnel(
    non_admin_client: AsyncClient,
) -> None:
    resp = await non_admin_client.post(
        "/api/v1/tunnels",
        json={
            "name": "blocked-edge",
            "endpoint_host": "1.2.3.4",
            "endpoint_port": 7843,
            "server_pubkey": _VALID_PUBKEY_B64,
        },
    )
    assert resp.status_code == 403
