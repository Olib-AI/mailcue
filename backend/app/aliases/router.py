"""Alias management router -- admin-only CRUD for email aliases."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.aliases.schemas import (
    AliasCreateRequest,
    AliasListResponse,
    AliasResponse,
    AliasUpdateRequest,
)
from app.aliases.service import (
    create_alias,
    delete_alias,
    get_alias,
    list_aliases,
    update_alias,
)
from app.auth.models import User
from app.database import get_db
from app.dependencies import require_admin

logger = logging.getLogger("mailcue.aliases")

router = APIRouter(prefix="/aliases", tags=["Aliases"])


@router.get("", response_model=AliasListResponse)
async def list_all_aliases(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AliasListResponse:
    """List all email aliases. **Admin only.**"""
    aliases = await list_aliases(db)
    return AliasListResponse(
        aliases=[AliasResponse.model_validate(a, from_attributes=True) for a in aliases],
        total=len(aliases),
    )


@router.post("", response_model=AliasResponse, status_code=status.HTTP_201_CREATED)
async def create_new_alias(
    body: AliasCreateRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AliasResponse:
    """Create a new email alias. **Admin only.**"""
    alias = await create_alias(body, db)
    return AliasResponse.model_validate(alias, from_attributes=True)


@router.get("/{alias_id}", response_model=AliasResponse)
async def get_one_alias(
    alias_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AliasResponse:
    """Get a single alias by ID. **Admin only.**"""
    alias = await get_alias(alias_id, db)
    return AliasResponse.model_validate(alias, from_attributes=True)


@router.put("/{alias_id}", response_model=AliasResponse)
async def update_existing_alias(
    alias_id: int,
    body: AliasUpdateRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AliasResponse:
    """Update an existing alias. **Admin only.**"""
    alias = await update_alias(alias_id, body, db)
    return AliasResponse.model_validate(alias, from_attributes=True)


@router.delete("/{alias_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_existing_alias(
    alias_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an alias. **Admin only.**"""
    await delete_alias(alias_id, db)
