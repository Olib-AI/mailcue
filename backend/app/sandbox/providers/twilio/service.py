"""Twilio-specific sandbox service helpers."""

from __future__ import annotations

import asyncio
import base64
import logging
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
    SandboxWebhookEndpoint,
)
from app.sandbox.service import resolve_provider_by_credential
from app.sandbox.signers import make_twilio_signer
from app.sandbox.webhook_raw import fire_and_forget, post_form

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("mailcue.sandbox.twilio")


async def resolve_account(
    db: AsyncSession, account_sid: str, auth_token: str
) -> SandboxProvider | None:
    """Resolve a Twilio account by matching both account_sid and auth_token."""
    provider = await resolve_provider_by_credential(db, "twilio", "account_sid", account_sid)
    if provider is None:
        return None
    if provider.credentials.get("auth_token") != auth_token:
        return None
    return provider


def extract_basic_auth(authorization: str | None) -> tuple[str, str] | None:
    """Extract username and password from a Basic auth header."""
    if not authorization or not authorization.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(authorization.removeprefix("Basic ").strip()).decode()
        username, _, password = decoded.partition(":")
        if not username:
            return None
        return username, password
    except Exception:
        return None


async def get_call(db: AsyncSession, provider_id: str, call_sid: str) -> SandboxCall | None:
    stmt = select(SandboxCall).where(
        SandboxCall.provider_id == provider_id,
        SandboxCall.external_id == call_sid,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_calls(db: AsyncSession, provider_id: str, limit: int = 50) -> list[SandboxCall]:
    stmt = (
        select(SandboxCall)
        .where(SandboxCall.provider_id == provider_id)
        .order_by(SandboxCall.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_call(
    db: AsyncSession,
    provider_id: str,
    call_sid: str,
    *,
    from_number: str,
    to_number: str,
    answer_url: str | None,
    answer_method: str,
    status_callback: str | None,
    status_callback_method: str,
    record: bool,
    raw_request: dict[str, Any],
) -> SandboxCall:
    call = SandboxCall(
        provider_id=provider_id,
        external_id=call_sid,
        direction="outbound",
        from_number=from_number,
        to_number=to_number,
        status="queued",
        answer_url=answer_url,
        answer_method=answer_method,
        status_callback=status_callback,
        status_callback_method=status_callback_method,
        record=record,
        raw_request=raw_request,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call


async def list_incoming_numbers(db: AsyncSession, provider_id: str) -> list[SandboxPhoneNumber]:
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


async def get_incoming_number(
    db: AsyncSession, provider_id: str, sid: str
) -> SandboxPhoneNumber | None:
    stmt = select(SandboxPhoneNumber).where(
        SandboxPhoneNumber.provider_id == provider_id,
        SandboxPhoneNumber.external_id == sid,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_incoming_number(
    db: AsyncSession,
    provider_id: str,
    sid: str,
    *,
    e164: str,
    friendly_name: str,
    iso_country: str,
    number_type: str,
    locality: str | None,
    region: str | None,
    capabilities: dict[str, bool],
    sms_url: str | None,
    voice_url: str | None,
    status_callback: str | None,
    raw_request: dict[str, Any],
) -> SandboxPhoneNumber:
    pn = SandboxPhoneNumber(
        provider_id=provider_id,
        external_id=sid,
        e164=e164,
        iso_country=iso_country,
        number_type=number_type,
        locality=locality,
        region=region,
        sms_url=sms_url,
        voice_url=voice_url,
        status_callback=status_callback,
        capabilities=capabilities,
        raw_request=raw_request,
        metadata_json={"friendly_name": friendly_name},
    )
    db.add(pn)
    await db.commit()
    await db.refresh(pn)
    return pn


async def list_port_orders(db: AsyncSession, provider_id: str) -> list[SandboxPortRequest]:
    stmt = (
        select(SandboxPortRequest)
        .where(SandboxPortRequest.provider_id == provider_id)
        .order_by(SandboxPortRequest.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_port_order(
    db: AsyncSession, provider_id: str, sid: str
) -> SandboxPortRequest | None:
    stmt = select(SandboxPortRequest).where(
        SandboxPortRequest.provider_id == provider_id,
        SandboxPortRequest.external_id == sid,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_port_order(
    db: AsyncSession,
    provider_id: str,
    sid: str,
    *,
    numbers: list[str],
    loa_info: dict[str, Any],
    raw_request: dict[str, Any],
) -> SandboxPortRequest:
    order = SandboxPortRequest(
        provider_id=provider_id,
        external_id=sid,
        status="submitted",
        numbers=numbers,
        loa_info=loa_info,
        raw_request=raw_request,
        metadata_json={"notification_emails": raw_request.get("notification_emails", [])},
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


async def create_brand(
    db: AsyncSession,
    provider_id: str,
    sid: str,
    *,
    brand_type: str,
    customer_profile_bundle_sid: str | None,
    a2p_profile_bundle_sid: str | None,
    raw_request: dict[str, Any],
) -> SandboxBrand:
    brand = SandboxBrand(
        provider_id=provider_id,
        external_id=sid,
        status="PENDING",
        company_name=raw_request.get("FriendlyName", ""),
        brand_data={
            "brand_type": brand_type,
            "customer_profile_bundle_sid": customer_profile_bundle_sid,
            "a2p_profile_bundle_sid": a2p_profile_bundle_sid,
        },
        raw_request=raw_request,
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
    *,
    description: str,
    use_case: str,
    sample_messages: list[str],
    raw_request: dict[str, Any],
) -> SandboxCampaign:
    campaign = SandboxCampaign(
        provider_id=provider_id,
        brand_id=brand_id,
        external_id=sid,
        status="PENDING",
        description=description,
        use_case=use_case,
        sample_messages=sample_messages,
        raw_request=raw_request,
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


# ── Webhook helpers ──────────────────────────────────────────────────────────


async def _webhook_urls_for_provider(db: AsyncSession, provider_id: str) -> list[str]:
    stmt = select(SandboxWebhookEndpoint).where(
        SandboxWebhookEndpoint.provider_id == provider_id,
        SandboxWebhookEndpoint.is_active.is_(True),
    )
    result = await db.execute(stmt)
    return [ep.url for ep in result.scalars().all()]


def schedule_brand_approval(
    db_factory: Any, provider_id: str, brand_sid: str, delay: float = 0.1
) -> None:
    """Asynchronously transition a brand to APPROVED after a short delay."""

    async def _transition() -> None:
        await asyncio.sleep(delay)
        async with db_factory() as db:
            brand = await get_brand(db, provider_id, brand_sid)
            if brand is None:
                return
            brand.status = "APPROVED"
            await db.commit()

    fire_and_forget(_transition())


def schedule_campaign_approval(
    db_factory: Any, provider_id: str, campaign_sid: str, delay: float = 0.1
) -> None:
    async def _transition() -> None:
        await asyncio.sleep(delay)
        async with db_factory() as db:
            campaign = await get_campaign(db, provider_id, campaign_sid)
            if campaign is None:
                return
            campaign.status = "APPROVED"
            await db.commit()

    fire_and_forget(_transition())


def schedule_port_lifecycle(
    db_factory: Any, provider_id: str, port_sid: str, statuses: list[str], delay: float = 0.05
) -> None:
    async def _transitions() -> None:
        for status in statuses:
            await asyncio.sleep(delay)
            async with db_factory() as db:
                order = await get_port_order(db, provider_id, port_sid)
                if order is None:
                    return
                order.status = status
                await db.commit()

    fire_and_forget(_transitions())


def schedule_call_status_callbacks(
    db_factory: Any,
    provider_id: str,
    call_sid: str,
    account_sid: str,
    auth_token: str | None,
    status_callback: str | None,
    events: list[tuple[str, str]],
    delay: float = 0.05,
) -> None:
    """Fire status callbacks for a series of (event_name, duration) events.

    Used when there is no answer URL — the call still transitions through
    the lifecycle and webhooks are emitted in Twilio's form-encoded format.
    """
    if status_callback is None:
        return

    async def _fire() -> None:
        for event, _duration in events:
            await asyncio.sleep(delay)
            payload = {
                "CallSid": call_sid,
                "AccountSid": account_sid,
                "CallStatus": event,
                "ApiVersion": "2010-04-01",
            }
            signer = None
            if auth_token:
                signer = make_twilio_signer(
                    auth_token=auth_token,
                    url=status_callback,
                    form_params=payload,
                )
            await post_form(status_callback, payload, signer=signer)

    fire_and_forget(_fire())


async def build_call_status_callback(
    db: AsyncSession,
    call: SandboxCall,
    account_sid: str,
    status: str,
    extra: dict[str, Any],
) -> None:
    """Invoke the per-call status_callback URL with Twilio form-encoded payload."""
    if call.status_callback is None:
        return
    payload: dict[str, Any] = {
        "AccountSid": account_sid,
        "CallSid": call.external_id,
        "CallStatus": status,
        "From": call.from_number,
        "To": call.to_number,
        "Direction": "outbound-api" if call.direction == "outbound" else "inbound",
        "ApiVersion": "2010-04-01",
    }
    if status == "completed":
        payload["CallDuration"] = call.duration_seconds
    payload.update({k: v for k, v in extra.items() if v is not None})

    # Sign with the owning account's auth_token if available so fase's
    # RequestValidator accepts the callback without sandbox-mode exceptions.
    provider = await db.get(SandboxProvider, call.provider_id)
    signer = None
    if provider is not None:
        auth_token = str(provider.credentials.get("auth_token") or "")
        if auth_token:
            signer = make_twilio_signer(
                auth_token=auth_token,
                url=call.status_callback,
                form_params=payload,
            )
    fire_and_forget(post_form(call.status_callback, payload, signer=signer))


def build_message_sid() -> str:
    return "SM" + __import__("uuid").uuid4().hex


def build_call_sid() -> str:
    return "CA" + __import__("uuid").uuid4().hex


def build_incoming_number_sid() -> str:
    return "PN" + __import__("uuid").uuid4().hex


def build_port_sid() -> str:
    return "PO" + __import__("uuid").uuid4().hex


def build_brand_sid() -> str:
    return "BN" + __import__("uuid").uuid4().hex


def build_campaign_sid() -> str:
    return "QE" + __import__("uuid").uuid4().hex


def build_customer_profile_sid() -> str:
    return "BU" + __import__("uuid").uuid4().hex


def now_iso() -> str:
    from datetime import UTC
    from datetime import datetime as _dt

    return _dt.now(UTC).isoformat()


__all__ = [
    "build_brand_sid",
    "build_call_sid",
    "build_call_status_callback",
    "build_campaign_sid",
    "build_customer_profile_sid",
    "build_incoming_number_sid",
    "build_message_sid",
    "build_port_sid",
    "create_brand",
    "create_call",
    "create_campaign",
    "create_incoming_number",
    "create_number_order",
    "create_port_order",
    "extract_basic_auth",
    "get_brand",
    "get_call",
    "get_campaign",
    "get_incoming_number",
    "get_port_order",
    "list_calls",
    "list_incoming_numbers",
    "list_port_orders",
    "now_iso",
    "resolve_account",
    "schedule_brand_approval",
    "schedule_call_status_callbacks",
    "schedule_campaign_approval",
    "schedule_port_lifecycle",
]


# used by webhook callbacks — kept here to avoid circular imports
def format_datetime(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    from email.utils import formatdate

    return formatdate(timeval=ts.timestamp(), localtime=False, usegmt=True)
