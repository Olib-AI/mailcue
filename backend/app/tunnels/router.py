"""Tunnels router -- admin-only CRUD plus client-identity and reload helpers."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.database import get_db
from app.dependencies import require_admin
from app.tunnels.schemas import (
    TunnelClientIdentityRequest,
    TunnelClientIdentityResponse,
    TunnelCreate,
    TunnelHealthCheckResponse,
    TunnelReloadConfigResponse,
    TunnelResponse,
    TunnelUpdate,
)
from app.tunnels.service import (
    create_tunnel,
    delete_tunnel,
    get_or_init_client_identity,
    get_tunnel,
    health_check,
    list_tunnels,
    set_client_identity,
    update_tunnel,
    write_tunnels_json,
)

logger = logging.getLogger("mailcue.tunnels")

router = APIRouter(prefix="/tunnels", tags=["Tunnels"])


# ── Client identity (must precede ``/{tunnel_id}`` routes) ───────


@router.get("/client-identity", response_model=TunnelClientIdentityResponse)
async def get_client_identity(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TunnelClientIdentityResponse:
    """Return the stored Mailcue tunnel-client public key. **Admin only.**"""
    row = await get_or_init_client_identity(db)
    return TunnelClientIdentityResponse.model_validate(row, from_attributes=True)


@router.put("/client-identity", response_model=TunnelClientIdentityResponse)
async def upsert_client_identity(
    body: TunnelClientIdentityRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TunnelClientIdentityResponse:
    """Upsert the Mailcue tunnel-client public key. **Admin only.**

    The admin pastes the value emitted by ``mailcue-relay-sidecar pubkey``;
    we recompute the SHA-256 fingerprint and store both for display.
    """
    row = await set_client_identity(body.public_key, db)
    return TunnelClientIdentityResponse.model_validate(row, from_attributes=True)


# ── Reload config helper ─────────────────────────────────────────


@router.post("/reload-config", response_model=TunnelReloadConfigResponse)
async def reload_tunnels_config(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TunnelReloadConfigResponse:
    """Force ``tunnels.json`` to be rewritten right now. **Admin only.**

    Useful when the sidecar's config volume becomes available after the
    API has already started -- e.g. running this immediately after the
    sidecar is deployed avoids waiting for the next CRUD operation.
    """
    written, path, reason = await write_tunnels_json(db)
    return TunnelReloadConfigResponse(written=written, path=path, reason=reason)


# ── Tunnel CRUD ──────────────────────────────────────────────────


@router.get("", response_model=list[TunnelResponse])
async def list_all_tunnels(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[TunnelResponse]:
    """List all configured tunnels. **Admin only.**"""
    tunnels = await list_tunnels(db)
    return [TunnelResponse.model_validate(t, from_attributes=True) for t in tunnels]


@router.post("", response_model=TunnelResponse, status_code=status.HTTP_201_CREATED)
async def create_new_tunnel(
    body: TunnelCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TunnelResponse:
    """Create a new tunnel. **Admin only.**"""
    tunnel = await create_tunnel(body, db)
    return TunnelResponse.model_validate(tunnel, from_attributes=True)


@router.get("/{tunnel_id}", response_model=TunnelResponse)
async def get_one_tunnel(
    tunnel_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TunnelResponse:
    """Fetch a single tunnel by ID. **Admin only.**"""
    tunnel = await get_tunnel(tunnel_id, db)
    return TunnelResponse.model_validate(tunnel, from_attributes=True)


@router.patch("/{tunnel_id}", response_model=TunnelResponse)
async def patch_tunnel(
    tunnel_id: str,
    body: TunnelUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TunnelResponse:
    """Apply a partial update to a tunnel. **Admin only.**"""
    tunnel = await update_tunnel(tunnel_id, body, db)
    return TunnelResponse.model_validate(tunnel, from_attributes=True)


@router.delete(
    "/{tunnel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_one_tunnel(
    tunnel_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete a tunnel. **Admin only.**"""
    await delete_tunnel(tunnel_id, db)


@router.post("/{tunnel_id}/check", response_model=TunnelHealthCheckResponse)
async def check_tunnel(
    tunnel_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TunnelHealthCheckResponse:
    """Probe a tunnel edge with a 5-second TCP connect. **Admin only.**

    The actual Noise IK handshake is the sidecar's responsibility -- this
    only confirms the edge port is reachable from the API host.
    """
    result = await health_check(tunnel_id, db)
    return TunnelHealthCheckResponse(**result)
