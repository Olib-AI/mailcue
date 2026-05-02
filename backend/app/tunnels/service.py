"""Tunnel business logic -- CRUD, ``tunnels.json`` writer, and health checks."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.tunnels.models import Tunnel, TunnelClientIdentity
from app.tunnels.schemas import TunnelCreate, TunnelUpdate

logger = logging.getLogger("mailcue.tunnels")

_SIDECAR_KEY_PATH = "/var/lib/mailcue-sidecar/client.key"
_TUNNELS_JSON_VERSION = 1
_DEFAULT_SELECTION = "round_robin"
_HEALTH_CHECK_TIMEOUT_SECONDS = 5.0


# ── CRUD ──────────────────────────────────────────────────────────


async def list_tunnels(db: AsyncSession) -> list[Tunnel]:
    """Return every tunnel ordered by ``name`` (case-sensitive)."""
    stmt = select(Tunnel).order_by(Tunnel.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_tunnel(tunnel_id: str, db: AsyncSession) -> Tunnel:
    """Fetch a single tunnel by ID or raise :class:`NotFoundError`."""
    tunnel = await db.get(Tunnel, tunnel_id)
    if tunnel is None:
        raise NotFoundError("Tunnel", tunnel_id)
    return tunnel


async def _get_tunnel_by_name(name: str, db: AsyncSession) -> Tunnel | None:
    stmt = select(Tunnel).where(Tunnel.name == name)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_tunnel(payload: TunnelCreate, db: AsyncSession) -> Tunnel:
    """Insert a new tunnel row and refresh the on-disk ``tunnels.json``."""
    if await _get_tunnel_by_name(payload.name, db) is not None:
        raise ConflictError(f"Tunnel '{payload.name}' already exists")

    tunnel = Tunnel(
        id=uuid.uuid4().hex,
        name=payload.name,
        endpoint_host=payload.endpoint_host,
        endpoint_port=payload.endpoint_port,
        server_pubkey=payload.server_pubkey,
        enabled=payload.enabled,
        weight=payload.weight,
        notes=payload.notes,
    )
    db.add(tunnel)
    await db.commit()
    await db.refresh(tunnel)

    await write_tunnels_json(db)
    logger.info("Tunnel '%s' created (id=%s).", tunnel.name, tunnel.id)
    return tunnel


async def update_tunnel(
    tunnel_id: str,
    payload: TunnelUpdate,
    db: AsyncSession,
) -> Tunnel:
    """Apply a partial update to the tunnel and refresh ``tunnels.json``."""
    tunnel = await get_tunnel(tunnel_id, db)

    update_data = payload.model_dump(exclude_unset=True)

    new_name = update_data.get("name")
    if new_name is not None and new_name != tunnel.name:
        clash = await _get_tunnel_by_name(new_name, db)
        if clash is not None and clash.id != tunnel.id:
            raise ConflictError(f"Tunnel '{new_name}' already exists")

    for field, value in update_data.items():
        setattr(tunnel, field, value)
    tunnel.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(tunnel)

    await write_tunnels_json(db)
    logger.info("Tunnel '%s' updated (id=%s).", tunnel.name, tunnel.id)
    return tunnel


async def delete_tunnel(tunnel_id: str, db: AsyncSession) -> None:
    """Delete the tunnel row and refresh ``tunnels.json``."""
    tunnel = await get_tunnel(tunnel_id, db)
    name = tunnel.name
    await db.delete(tunnel)
    await db.commit()

    await write_tunnels_json(db)
    logger.info("Tunnel '%s' deleted (id=%s).", name, tunnel_id)


# ── Client identity ──────────────────────────────────────────────


async def get_or_init_client_identity(db: AsyncSession) -> TunnelClientIdentity:
    """Return the singleton client identity row, creating an empty one if needed.

    The sidecar bootstraps the keypair on first run and the admin pastes
    the resulting public key back via :func:`set_client_identity`.  This
    module never generates keys.
    """
    stmt = select(TunnelClientIdentity).where(TunnelClientIdentity.id == 1)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        return row

    row = TunnelClientIdentity(id=1, public_key=None, fingerprint=None, updated_at=None)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _compute_fingerprint(public_key_b64: str) -> str:
    """Return ``sha256(raw_pubkey).hexdigest()[:32]`` for display."""
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError(f"public_key is not valid base64: {exc}") from exc
    if len(raw) != 32:
        raise ValidationError(f"public_key must decode to 32 bytes (got {len(raw)}).")
    return hashlib.sha256(raw).hexdigest()[:32]


async def set_client_identity(
    public_key: str,
    db: AsyncSession,
) -> TunnelClientIdentity:
    """Upsert the client-identity row.  Validates the pubkey shape."""
    fingerprint = _compute_fingerprint(public_key)

    row = await get_or_init_client_identity(db)
    row.public_key = public_key
    row.fingerprint = fingerprint
    row.updated_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(row)
    logger.info("Tunnel client identity updated (fingerprint=%s).", fingerprint)
    return row


# ── tunnels.json writer ──────────────────────────────────────────


def _build_tunnels_payload(tunnels: list[Tunnel]) -> dict[str, Any]:
    """Build the on-disk JSON document consumed by ``mailcue-relay-sidecar``.

    Schema mirrors ``tunnel/crates/sidecar/src/tunnels.rs``: the sidecar's
    deserializer expects ``host`` + ``port`` as separate fields and
    ``edge_pubkey`` (not ``server_pubkey``).
    """
    return {
        "version": _TUNNELS_JSON_VERSION,
        "client_static_key_path": _SIDECAR_KEY_PATH,
        "selection": _DEFAULT_SELECTION,
        "tunnels": [
            {
                "id": t.id,
                "name": t.name,
                "host": t.endpoint_host,
                "port": int(t.endpoint_port),
                "edge_pubkey": t.server_pubkey,
                "enabled": bool(t.enabled),
                "weight": int(t.weight),
            }
            for t in sorted(tunnels, key=lambda x: x.name)
        ],
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write *payload* atomically to *path* with mode ``0o640``.

    Any :class:`OSError` is propagated; the caller is responsible for
    converting it into graceful-degradation behaviour.
    """
    parent = path.parent
    if not parent.exists():
        raise OSError(f"Tunnels config directory does not exist: {parent}")

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    serialized = json.dumps(payload, indent=2, sort_keys=False) + "\n"

    fd = os.open(
        tmp_path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o640,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(serialized)
    except Exception:
        # Best-effort cleanup so we never leave a half-written ``.tmp``.
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise

    # Non-fatal -- some filesystems (e.g. tmpfs in tests) reject chmod.
    with contextlib.suppress(OSError):
        os.chmod(tmp_path, 0o640)

    os.replace(tmp_path, path)


async def write_tunnels_json(
    db: AsyncSession,
    *,
    path: Path | None = None,
) -> tuple[bool, str, str | None]:
    """Render every tunnel to the sidecar's JSON config file.

    Returns ``(written, path, reason)`` so the API can echo why the
    operation degraded gracefully.  When the destination directory is
    missing or unwritable, a warning is logged and ``written=False`` is
    returned -- the caller must NOT fail.
    """
    target = path if path is not None else Path(settings.tunnels_config_path)

    tunnels = await list_tunnels(db)
    payload = _build_tunnels_payload(tunnels)

    def _do_write() -> None:
        _atomic_write_json(target, payload)

    try:
        await asyncio.to_thread(_do_write)
    except (OSError, PermissionError) as exc:
        logger.warning(
            "Skipped writing tunnels.json to %s: %s (sidecar likely not deployed).",
            target,
            exc,
        )
        return False, str(target), str(exc)

    logger.info("Wrote %d tunnel(s) to %s.", len(tunnels), target)
    return True, str(target), None


# ── Health check ─────────────────────────────────────────────────


async def health_check(tunnel_id: str, db: AsyncSession) -> dict[str, Any]:
    """Probe the tunnel edge with a TCP connect (no Noise handshake)."""
    tunnel = await get_tunnel(tunnel_id, db)

    checked_at = datetime.now(UTC)
    ok = False
    message = ""
    writer: asyncio.StreamWriter | None = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(tunnel.endpoint_host, tunnel.endpoint_port),
            timeout=_HEALTH_CHECK_TIMEOUT_SECONDS,
        )
        ok = True
        message = f"TCP connect to {tunnel.endpoint_host}:{tunnel.endpoint_port} succeeded."
    except TimeoutError:
        message = (
            f"TCP connect to {tunnel.endpoint_host}:{tunnel.endpoint_port} "
            f"timed out after {_HEALTH_CHECK_TIMEOUT_SECONDS}s."
        )
    except OSError as exc:
        message = f"TCP connect to {tunnel.endpoint_host}:{tunnel.endpoint_port} failed: {exc}"
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError, asyncio.CancelledError):
                await writer.wait_closed()

    tunnel.last_checked_at = checked_at
    tunnel.last_check_ok = ok
    tunnel.last_check_message = message
    await db.commit()

    return {
        "tunnel_id": tunnel.id,
        "ok": ok,
        "message": message,
        "checked_at": checked_at,
    }
