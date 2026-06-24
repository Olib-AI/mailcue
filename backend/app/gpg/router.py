"""GPG key management API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import scopes
from app.database import get_db
from app.dependencies import AuthContext, get_auth, require_scope
from app.gpg import service as gpg_service
from app.gpg.schemas import (
    GenerateKeyRequest,
    GpgKeyExportResponse,
    GpgKeyListResponse,
    GpgKeyResponse,
    ImportKeyRequest,
    KeyserverPublishResponse,
)
from app.mailboxes.router import verify_mailbox_access

router = APIRouter(prefix="/gpg", tags=["GPG"])


@router.post(
    "/keys/generate",
    response_model=GpgKeyResponse,
    status_code=201,
    dependencies=[Depends(require_scope(scopes.GPG_MANAGE))],
)
async def generate_key(
    request: GenerateKeyRequest,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> GpgKeyResponse:
    """Generate a new GPG keypair for a mailbox address.

    The user must own the target mailbox (admins may target any).
    """
    await verify_mailbox_access(request.mailbox_address, auth, db)
    try:
        return await gpg_service.generate_key(request, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get(
    "/keys",
    response_model=GpgKeyListResponse,
    dependencies=[Depends(require_scope(scopes.GPG_READ))],
)
async def list_keys(
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> GpgKeyListResponse:
    """List GPG keys for the current user's mailboxes only."""
    result = await gpg_service.list_keys(db)
    from app.mailboxes.service import list_mailboxes

    owned = await list_mailboxes(db, user=auth.user)
    owned_addresses = {m.address.lower() for m in owned}
    filtered = [k for k in result.keys if k.mailbox_address.lower() in owned_addresses]
    return GpgKeyListResponse(keys=filtered, total=len(filtered))


@router.get(
    "/keys/{address}",
    response_model=GpgKeyResponse,
    dependencies=[Depends(require_scope(scopes.GPG_READ))],
)
async def get_key(
    address: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> GpgKeyResponse:
    """Retrieve a GPG key by mailbox address."""
    await verify_mailbox_access(address, auth, db)
    key = await gpg_service.get_key_for_address(address, db)
    if not key:
        raise HTTPException(status_code=404, detail=f"No key found for {address}")
    return key


@router.get(
    "/keys/{address}/export",
    response_model=GpgKeyExportResponse,
    dependencies=[Depends(require_scope(scopes.GPG_READ))],
)
async def export_key(
    address: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> GpgKeyExportResponse:
    """Export the ASCII-armored public key for a mailbox address."""
    await verify_mailbox_access(address, auth, db)
    try:
        return await gpg_service.export_public_key(address, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get(
    "/keys/{address}/export/raw",
    dependencies=[Depends(require_scope(scopes.GPG_READ))],
)
async def export_key_raw(
    address: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download the raw armored PGP public key as a ``.asc`` file."""
    await verify_mailbox_access(address, auth, db)
    try:
        export = await gpg_service.export_public_key(address, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(
        content=export.public_key,
        media_type="application/pgp-keys",
        headers={"Content-Disposition": f'attachment; filename="{address}.asc"'},
    )


@router.post(
    "/keys/{address}/publish",
    response_model=KeyserverPublishResponse,
    dependencies=[Depends(require_scope(scopes.GPG_MANAGE))],
)
async def publish_key(
    address: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> KeyserverPublishResponse:
    """Publish a GPG public key to keys.openpgp.org."""
    await verify_mailbox_access(address, auth, db)
    try:
        return await gpg_service.publish_to_keyserver(address, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post(
    "/keys/import",
    response_model=GpgKeyResponse,
    status_code=201,
    dependencies=[Depends(require_scope(scopes.GPG_MANAGE))],
)
async def import_key(
    request: ImportKeyRequest,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> GpgKeyResponse:
    """Import an armored PGP public key.

    If ``mailbox_address`` is specified, the user must own that mailbox.
    """
    if request.mailbox_address:
        await verify_mailbox_access(request.mailbox_address, auth, db)
    try:
        return await gpg_service.import_key(request, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete(
    "/keys/{address}",
    status_code=204,
    response_model=None,
    dependencies=[Depends(require_scope(scopes.GPG_MANAGE))],
)
async def delete_key(
    address: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete all GPG keys for a mailbox address."""
    await verify_mailbox_access(address, auth, db)
    try:
        await gpg_service.delete_key(address, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
