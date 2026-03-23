"""Alias management business logic -- CRUD and Postfix virtual alias map generation."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aliases.models import Alias
from app.aliases.schemas import AliasCreateRequest, AliasUpdateRequest
from app.exceptions import ConflictError, NotFoundError

logger = logging.getLogger("mailcue.aliases")


async def list_aliases(db: AsyncSession) -> list[Alias]:
    """Return all aliases ordered by creation date descending."""
    stmt = select(Alias).order_by(Alias.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_alias(alias_id: int, db: AsyncSession) -> Alias:
    """Fetch a single alias by ID or raise ``NotFoundError``."""
    alias = await db.get(Alias, alias_id)
    if alias is None:
        raise NotFoundError("Alias", str(alias_id))
    return alias


async def create_alias(body: AliasCreateRequest, db: AsyncSession) -> Alias:
    """Create a new alias and rebuild Postfix virtual alias maps."""
    # Determine domain and catch-all status
    local_part, domain = body.source_address.rsplit("@", maxsplit=1)
    is_catchall = local_part == ""

    # Check uniqueness
    stmt = select(Alias).where(Alias.source_address == body.source_address)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise ConflictError(f"Alias '{body.source_address}' already exists")

    alias = Alias(
        source_address=body.source_address,
        destination_address=body.destination_address,
        domain=domain,
        is_catchall=is_catchall,
    )
    db.add(alias)
    await db.commit()
    await db.refresh(alias)

    await rebuild_postfix_virtual_aliases(db)
    logger.info("Alias '%s' -> '%s' created.", body.source_address, body.destination_address)
    return alias


async def update_alias(alias_id: int, body: AliasUpdateRequest, db: AsyncSession) -> Alias:
    """Update an existing alias and rebuild Postfix virtual alias maps."""
    alias = await get_alias(alias_id, db)

    if body.destination_address is not None:
        alias.destination_address = body.destination_address
    if body.enabled is not None:
        alias.enabled = body.enabled

    await db.commit()
    await db.refresh(alias)

    await rebuild_postfix_virtual_aliases(db)
    logger.info("Alias id=%d updated.", alias_id)
    return alias


async def delete_alias(alias_id: int, db: AsyncSession) -> None:
    """Delete an alias and rebuild Postfix virtual alias maps."""
    alias = await get_alias(alias_id, db)
    await db.delete(alias)
    await db.commit()

    await rebuild_postfix_virtual_aliases(db)
    logger.info("Alias id=%d ('%s') deleted.", alias_id, alias.source_address)


async def rebuild_postfix_virtual_aliases(db: AsyncSession) -> None:
    """Regenerate ``/etc/postfix/virtual_aliases`` from the database.

    Each enabled alias produces a line ``source destination``.
    After writing, ``postmap`` is invoked to build the hash DB.
    """
    stmt = select(Alias).where(Alias.enabled.is_(True))
    result = await db.execute(stmt)
    aliases = list(result.scalars().all())

    def _write() -> None:
        valias_path = Path("/etc/postfix/virtual_aliases")
        lines = [f"{a.source_address}    {a.destination_address}" for a in aliases]
        valias_path.write_text("\n".join(lines) + "\n")
        subprocess.run(
            ["postmap", str(valias_path)],
            check=False,
            capture_output=True,
        )

    await asyncio.to_thread(_write)
    logger.info("Rebuilt /etc/postfix/virtual_aliases with %d entries.", len(aliases))
