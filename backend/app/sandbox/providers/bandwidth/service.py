"""Bandwidth credential resolution + sandbox helpers."""

from __future__ import annotations

import asyncio
import base64
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.sandbox.models import (
    SandboxBrand,
    SandboxCall,
    SandboxCampaign,
    SandboxNumberOrder,
    SandboxPhoneNumber,
    SandboxPortRequest,
    SandboxProvider,
)
from app.sandbox.service import resolve_provider_by_credential
from app.sandbox.webhook_raw import fire_and_forget

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def extract_basic_auth(authorization: str | None) -> tuple[str, str] | None:
    if not authorization or not authorization.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(authorization.removeprefix("Basic ").strip()).decode()
        user, _, password = decoded.partition(":")
        if not user:
            return None
        return user, password
    except Exception:
        return None


async def resolve_account(
    db: AsyncSession, account_id: str, username: str, password: str
) -> SandboxProvider | None:
    provider = await resolve_provider_by_credential(db, "bandwidth", "account_id", account_id)
    if provider is None:
        return None
    creds = provider.credentials
    if creds.get("username") != username or creds.get("password") != password:
        return None
    return provider


async def resolve_by_auth_only(
    db: AsyncSession, username: str, password: str
) -> SandboxProvider | None:
    provider = await resolve_provider_by_credential(db, "bandwidth", "username", username)
    if provider is None:
        return None
    if provider.credentials.get("password") != password:
        return None
    return provider


async def create_number_order(
    db: AsyncSession,
    provider_id: str,
    sid: str,
    *,
    numbers: list[str],
    raw_request: dict[str, Any],
) -> SandboxNumberOrder:
    order = SandboxNumberOrder(
        provider_id=provider_id,
        external_id=sid,
        status="COMPLETE",
        numbers=numbers,
        raw_request=raw_request,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


async def get_order(db: AsyncSession, provider_id: str, sid: str) -> SandboxNumberOrder | None:
    stmt = select(SandboxNumberOrder).where(
        SandboxNumberOrder.provider_id == provider_id,
        SandboxNumberOrder.external_id == sid,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_owned_numbers(db: AsyncSession, provider_id: str) -> list[SandboxPhoneNumber]:
    stmt = (
        select(SandboxPhoneNumber)
        .where(
            SandboxPhoneNumber.provider_id == provider_id,
            SandboxPhoneNumber.released.is_(False),
        )
        .order_by(SandboxPhoneNumber.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_number_by_e164(
    db: AsyncSession, provider_id: str, e164: str
) -> SandboxPhoneNumber | None:
    stmt = select(SandboxPhoneNumber).where(
        SandboxPhoneNumber.provider_id == provider_id,
        SandboxPhoneNumber.e164 == e164,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_phone_number(
    db: AsyncSession,
    provider_id: str,
    sid: str,
    *,
    e164: str,
    iso_country: str = "US",
    number_type: str = "local",
    locality: str | None = None,
    region: str | None = None,
    capabilities: dict[str, bool],
) -> SandboxPhoneNumber:
    pn = SandboxPhoneNumber(
        provider_id=provider_id,
        external_id=sid,
        e164=e164,
        iso_country=iso_country,
        number_type=number_type,
        locality=locality,
        region=region,
        capabilities=capabilities,
    )
    db.add(pn)
    await db.commit()
    await db.refresh(pn)
    return pn


async def create_port_order(
    db: AsyncSession,
    provider_id: str,
    sid: str,
    *,
    numbers: list[str],
    loa_info: dict[str, Any],
    raw_request: dict[str, Any],
    customer_order_id: str = "",
) -> SandboxPortRequest:
    order = SandboxPortRequest(
        provider_id=provider_id,
        external_id=sid,
        status="RECEIVED",
        numbers=numbers,
        loa_info=loa_info,
        raw_request=raw_request,
        metadata_json={"customer_order_id": customer_order_id},
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


async def get_port_order(
    db: AsyncSession, provider_id: str, sid: str
) -> SandboxPortRequest | None:
    stmt = select(SandboxPortRequest).where(
        SandboxPortRequest.provider_id == provider_id,
        SandboxPortRequest.external_id == sid,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_brand(
    db: AsyncSession,
    provider_id: str,
    sid: str,
    raw_request: dict[str, Any],
) -> SandboxBrand:
    brand = SandboxBrand(
        provider_id=provider_id,
        external_id=sid,
        status="PENDING",
        company_name=raw_request.get("companyName", raw_request.get("displayName", "")),
        ein=raw_request.get("ein"),
        brand_data=dict(raw_request),
        raw_request=dict(raw_request),
    )
    db.add(brand)
    await db.commit()
    await db.refresh(brand)
    return brand


async def get_brand(db: AsyncSession, provider_id: str, sid: str) -> SandboxBrand | None:
    stmt = select(SandboxBrand).where(
        SandboxBrand.provider_id == provider_id,
        SandboxBrand.external_id == sid,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_campaign(
    db: AsyncSession,
    provider_id: str,
    sid: str,
    brand_id: str | None,
    raw_request: dict[str, Any],
) -> SandboxCampaign:
    campaign = SandboxCampaign(
        provider_id=provider_id,
        brand_id=brand_id,
        external_id=sid,
        status="PENDING",
        use_case=raw_request.get("usecase", "MIXED"),
        description=raw_request.get("description", ""),
        sample_messages=list(raw_request.get("sampleMessages", [])),
        raw_request=dict(raw_request),
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def get_campaign(db: AsyncSession, provider_id: str, sid: str) -> SandboxCampaign | None:
    stmt = select(SandboxCampaign).where(
        SandboxCampaign.provider_id == provider_id,
        SandboxCampaign.external_id == sid,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_call(
    db: AsyncSession,
    provider_id: str,
    call_id: str,
    *,
    from_number: str,
    to_number: str,
    application_id: str,
    answer_url: str | None,
    answer_method: str,
    disconnect_url: str | None,
    raw_request: dict[str, Any],
) -> SandboxCall:
    call = SandboxCall(
        provider_id=provider_id,
        external_id=call_id,
        direction="outbound",
        from_number=from_number,
        to_number=to_number,
        status="queued",
        answer_url=answer_url,
        answer_method=answer_method,
        status_callback=disconnect_url,
        status_callback_method="POST",
        raw_request=raw_request,
        metadata_json={
            "application_id": application_id,
            "disconnect_url": disconnect_url,
        },
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call


async def get_call(db: AsyncSession, provider_id: str, call_id: str) -> SandboxCall | None:
    stmt = select(SandboxCall).where(
        SandboxCall.provider_id == provider_id,
        SandboxCall.external_id == call_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_calls_for(db: AsyncSession, provider_id: str, limit: int = 50) -> list[SandboxCall]:
    stmt = (
        select(SandboxCall)
        .where(SandboxCall.provider_id == provider_id)
        .order_by(SandboxCall.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ── Lifecycle schedulers ────────────────────────────────────────────────────


def schedule_brand_approval(
    db_factory: async_sessionmaker[Any],
    provider_id: str,
    brand_sid: str,
    delay: float = 0.1,
) -> None:
    async def _t() -> None:
        await asyncio.sleep(delay)
        async with db_factory() as db:
            brand = await get_brand(db, provider_id, brand_sid)
            if brand is None:
                return
            brand.status = "APPROVED"
            await db.commit()

    fire_and_forget(_t())


def schedule_campaign_approval(
    db_factory: async_sessionmaker[Any],
    provider_id: str,
    campaign_sid: str,
    delay: float = 0.1,
) -> None:
    async def _t() -> None:
        await asyncio.sleep(delay)
        async with db_factory() as db:
            campaign = await get_campaign(db, provider_id, campaign_sid)
            if campaign is None:
                return
            campaign.status = "APPROVED"
            await db.commit()

    fire_and_forget(_t())


def schedule_port_lifecycle(
    db_factory: async_sessionmaker[Any],
    provider_id: str,
    sid: str,
    statuses: list[str],
    delay: float = 0.05,
) -> None:
    async def _t() -> None:
        for status in statuses:
            await asyncio.sleep(delay)
            async with db_factory() as db:
                order = await get_port_order(db, provider_id, sid)
                if order is None:
                    return
                order.status = status
                await db.commit()

    fire_and_forget(_t())


__all__ = [
    "create_brand",
    "create_call",
    "create_campaign",
    "create_number_order",
    "create_phone_number",
    "create_port_order",
    "extract_basic_auth",
    "get_brand",
    "get_call",
    "get_campaign",
    "get_number_by_e164",
    "get_order",
    "get_port_order",
    "list_calls_for",
    "list_owned_numbers",
    "resolve_account",
    "resolve_by_auth_only",
    "schedule_brand_approval",
    "schedule_campaign_approval",
    "schedule_port_lifecycle",
]
