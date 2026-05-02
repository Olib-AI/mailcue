"""Domain management router — admin-only CRUD + DNS verification."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.database import get_db
from app.dependencies import require_admin
from app.domains.models import Domain
from app.domains.schemas import (
    DnsCheckResponse,
    DomainCreateRequest,
    DomainDetailResponse,
    DomainDnsStateResponse,
    DomainListResponse,
    DomainResponse,
)
from app.domains.service import (
    _build_dns_records,
    add_domain,
    compute_dns_state,
    get_domain_detail,
    list_domains,
    remove_domain,
    verify_dns,
)
from app.system.service import get_server_hostname

logger = logging.getLogger("mailcue.domains")

router = APIRouter(prefix="/domains", tags=["Domains"])


def _domain_to_response(domain: Domain) -> DomainResponse:
    """Convert a Domain model to a DomainResponse."""
    return DomainResponse(
        id=domain.id,
        name=domain.name,
        is_active=domain.is_active,
        created_at=domain.created_at,
        dkim_selector=domain.dkim_selector,
        mx_verified=domain.mx_verified,
        spf_verified=domain.spf_verified,
        dkim_verified=domain.dkim_verified,
        dmarc_verified=domain.dmarc_verified,
        mta_sts_verified=domain.mta_sts_verified,
        tls_rpt_verified=domain.tls_rpt_verified,
        last_dns_check=domain.last_dns_check,
        all_verified=all(
            [
                domain.mx_verified,
                domain.spf_verified,
                domain.dkim_verified,
                domain.dmarc_verified,
                domain.mta_sts_verified,
                domain.tls_rpt_verified,
            ]
        ),
    )


@router.get("", response_model=DomainListResponse)
async def list_all_domains(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DomainListResponse:
    """List all managed email domains. **Admin only.**"""
    domains = await list_domains(db)
    return DomainListResponse(
        domains=[_domain_to_response(d) for d in domains],
        total=len(domains),
    )


@router.post("", response_model=DomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(
    body: DomainCreateRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DomainResponse:
    """Add a new email domain and generate DKIM keys. **Admin only.**"""
    # Check for existing domain
    stmt = select(Domain).where(Domain.name == body.name)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Domain '{body.name}' already exists",
        )

    domain = await add_domain(body.name, body.dkim_selector, db)
    return _domain_to_response(domain)


@router.get("/{name}", response_model=DomainDetailResponse)
async def get_domain(
    name: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DomainDetailResponse:
    """Get domain details including required DNS records. **Admin only.**"""
    try:
        domain = await get_domain_detail(name, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    hostname = await get_server_hostname(db)

    # Run quick checks for records not persisted in the domain model
    from app.domains.service import _check_bimi, _check_helo_spf

    helo_result, bimi_result = await asyncio.gather(
        _check_helo_spf(hostname),
        _check_bimi(domain.name),
    )
    dns_records = _build_dns_records(
        domain,
        hostname,
        helo_spf_verified=helo_result[0],
        bimi_verified=bimi_result[0],
    )

    return DomainDetailResponse(
        id=domain.id,
        name=domain.name,
        is_active=domain.is_active,
        created_at=domain.created_at,
        dkim_selector=domain.dkim_selector,
        mx_verified=domain.mx_verified,
        spf_verified=domain.spf_verified,
        dkim_verified=domain.dkim_verified,
        dmarc_verified=domain.dmarc_verified,
        mta_sts_verified=domain.mta_sts_verified,
        tls_rpt_verified=domain.tls_rpt_verified,
        last_dns_check=domain.last_dns_check,
        all_verified=all(
            [
                domain.mx_verified,
                domain.spf_verified,
                domain.dkim_verified,
                domain.dmarc_verified,
                domain.mta_sts_verified,
                domain.tls_rpt_verified,
            ]
        ),
        dns_records=dns_records,
        dkim_public_key_txt=domain.dkim_public_key_txt,
    )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_domain(
    name: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a managed domain and clean up config. **Admin only.**"""
    try:
        await remove_domain(name, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/.well-known/mta-sts.txt", response_class=PlainTextResponse)
async def mta_sts_policy(
    db: AsyncSession = Depends(get_db),
) -> str:
    """Serve the MTA-STS policy file (RFC 8461).

    This must be accessible at https://mta-sts.{domain}/.well-known/mta-sts.txt
    for each managed domain.
    """
    hostname = await get_server_hostname(db)
    return f"version: STSv1\nmode: testing\nmx: {hostname}\nmax_age: 86400\n"


@router.post("/{name}/verify-dns", response_model=DnsCheckResponse)
async def verify_domain_dns(
    name: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DnsCheckResponse:
    """Run live DNS checks for a domain. **Admin only.**"""
    try:
        return await verify_dns(name, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/{name}/dns-state", response_model=DomainDnsStateResponse)
async def get_dns_state(
    name: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DomainDnsStateResponse:
    """Refresh DNS lookups + return per-record expected/published/drift state.

    Read-only: never flips the canonical ``*_verified`` booleans (use
    ``POST /verify-dns`` for that).  Designed to be cheap and pollable from
    the admin UI every 60s.  **Admin only.**
    """
    try:
        return await compute_dns_state(name, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
