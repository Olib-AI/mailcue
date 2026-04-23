"""Telnyx v2 sandbox router: messages, calls, numbers, porting, TCR."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.sandbox.models import (
    SandboxBrand,
    SandboxCall,
    SandboxCampaign,
    SandboxMessage,
    SandboxNumberOrder,
    SandboxPhoneNumber,
    SandboxPortRequest,
)
from app.sandbox.providers.base import BaseSandboxProvider
from app.sandbox.providers.telnyx import formatter as fmt
from app.sandbox.providers.telnyx.service import (
    ensure_keypair,
    resolve_bearer,
    sign_webhook,
)
from app.sandbox.seeds.available_numbers import (
    get_available_numbers,
    mark_consumed,
    release_consumed,
)
from app.sandbox.service import (
    get_or_create_conversation,
    store_message,
    update_raw_response,
)
from app.sandbox.voice.worker import start_call
from app.sandbox.webhook_raw import fire_and_forget, post_json

logger = logging.getLogger("mailcue.sandbox.telnyx")

router = APIRouter(prefix="/sandbox/telnyx", tags=["Sandbox - Telnyx"])


def _unauth() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "errors": [
                {
                    "code": "10015",
                    "title": "Unauthorized",
                    "detail": "Invalid API key",
                }
            ]
        },
    )


async def _resolve(db: AsyncSession, authorization: str | None) -> Any:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    provider = await resolve_bearer(db, token)
    if provider is None:
        return None
    # Ensure we have an Ed25519 keypair for webhook signing
    before = dict(provider.credentials)
    ensure_keypair(provider)
    if provider.credentials != before:
        await db.commit()
    return provider


def _telnyx_signer(priv_b64: str):
    async def sign(headers: dict[str, str], body: bytes) -> dict[str, str]:
        ts = str(int(datetime.now(UTC).timestamp()))
        sig = sign_webhook(priv_b64, body, ts)
        return {
            **headers,
            "telnyx-timestamp": ts,
            "telnyx-signature-ed25519": sig,
        }

    return sign


# ─────────────────────────────────────────────────────────────────────────────
# Webhook signing key endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/v2/public_key")
async def get_public_key(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    _priv, pub = ensure_keypair(provider)
    await db.commit()
    return {"data": {"public_key": pub}}


# ─────────────────────────────────────────────────────────────────────────────
# Messages
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/v2/messages")
async def send_message(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={"errors": [{"detail": "bad body"}]})
    to_raw = body.get("to")
    to_list = to_raw if isinstance(to_raw, list) else ([to_raw] if to_raw else [])
    from_number = body.get("from", "")
    text = body.get("text", "")
    media = body.get("media_urls") or []
    if isinstance(media, str):
        media = [media]

    msg_id = fmt.new_message_id()
    conv_ext = f"{from_number}->{','.join(to_list)}"
    conv = await get_or_create_conversation(db, provider.id, conv_ext, conv_ext, "sms")
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        from_number,
        text,
        conversation_id=conv.id,
        content_type="mms" if media else "sms",
        external_id=msg_id,
        raw_request=body,
        metadata={
            "from": from_number,
            "to": to_list,
            "messaging_profile_id": body.get("messaging_profile_id"),
            "media_urls": media,
            "webhook_url": body.get("webhook_url"),
        },
    )
    response = fmt.format_message(msg)
    await update_raw_response(db, msg, response)
    return JSONResponse(status_code=200, content=response)


@router.get("/v2/messages/{message_id}")
async def fetch_message(
    message_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxMessage).where(
        SandboxMessage.provider_id == provider.id,
        SandboxMessage.external_id == message_id,
    )
    result = await db.execute(stmt)
    msg = result.scalar_one_or_none()
    if msg is None:
        return JSONResponse(status_code=404, content={"errors": [{"detail": "not found"}]})
    return fmt.format_message(msg)


@router.get("/v2/messages")
async def list_messages(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    limit: int = Query(default=20, alias="page[size]"),
) -> Any:
    from app.sandbox.service import get_messages

    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    messages, total = await get_messages(db, provider.id, limit=limit)
    return {
        "data": [fmt.format_message(m)["data"] for m in messages],
        "meta": {
            "total_pages": 1,
            "total_results": total,
            "page_number": 1,
            "page_size": limit,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Calls
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/v2/calls")
async def create_call(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={"errors": [{"detail": "bad body"}]})
    from_number = body.get("from", "")
    to = body.get("to", "")
    webhook_url = body.get("webhook_url") or body.get("answer_url")
    call_id = fmt.new_call_id()
    call_control_id = fmt.new_call_control_id()

    call = SandboxCall(
        provider_id=provider.id,
        external_id=call_id,
        direction="outbound",
        from_number=from_number,
        to_number=to,
        status="parked",
        answer_url=webhook_url,
        answer_method="POST",
        status_callback=webhook_url,
        status_callback_method="POST",
        raw_request=body,
        metadata_json={
            "call_control_id": call_control_id,
            "client_state": body.get("client_state"),
        },
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)

    priv_b64, _pub = ensure_keypair(provider)
    await db.commit()
    signer = _telnyx_signer(priv_b64)

    async def _cb(status: str, call_snap: Any, extra: dict[str, Any]) -> None:
        url = call_snap.status_callback
        if not url:
            return
        event_map = {
            "initiated": "call.initiated",
            "answered": "call.answered",
            "completed": "call.hangup",
            "failed": "call.hangup",
            "canceled": "call.hangup",
            "ringing": "call.ringing",
        }
        event = event_map.get(status)
        if event is None:
            return
        payload = {
            "data": {
                "event_type": event,
                "id": fmt.new_call_id(),
                "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "payload": {
                    "call_control_id": call_snap.metadata_json.get(
                        "call_control_id", call_snap.external_id
                    ),
                    "call_leg_id": call_snap.external_id,
                    "call_session_id": call_snap.external_id,
                    "client_state": call_snap.metadata_json.get("client_state"),
                    "from": call_snap.from_number,
                    "to": call_snap.to_number,
                    "direction": "outgoing",
                    "state": {
                        "call.initiated": "parked",
                        "call.ringing": "ringing",
                        "call.answered": "answered",
                        "call.hangup": "hangup",
                    }.get(event, "hangup"),
                },
                "record_type": "event",
            }
        }
        await post_json(url, payload, signer=signer)

    start_call(
        call_id=call.id,
        provider_type="telnyx",
        seed_digits=provider.credentials.get("sandbox_seed_digits", "1"),
        seed_speech=provider.credentials.get("sandbox_seed_speech", "yes"),
        status_cb=_cb,
    )

    return {
        "data": {
            "call_control_id": call_control_id,
            "call_leg_id": call_id,
            "call_session_id": call_id,
            "is_alive": True,
            "record_type": "call",
        }
    }


@router.get("/v2/calls/{call_id}")
async def fetch_call(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxCall).where(
        SandboxCall.provider_id == provider.id,
        SandboxCall.external_id == call_id,
    )
    result = await db.execute(stmt)
    call = result.scalar_one_or_none()
    if call is None:
        return JSONResponse(status_code=404, content={"errors": [{"detail": "not found"}]})
    return fmt.format_call(call)


@router.post("/v2/calls/{call_control_id}/actions/hangup")
async def call_action_hangup(
    call_control_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxCall).where(SandboxCall.provider_id == provider.id)
    result = await db.execute(stmt)
    for c in result.scalars().all():
        if c.metadata_json.get("call_control_id") == call_control_id:
            c.status = "completed"
            await db.commit()
            return {"data": {"result": "ok"}}
    return JSONResponse(status_code=404, content={"errors": [{"detail": "not found"}]})


@router.post("/v2/calls/{call_control_id}/actions/speak")
async def call_action_speak(
    call_control_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    _body = await request.json()
    return {"data": {"result": "ok"}}


@router.post("/v2/calls/{call_control_id}/actions/gather_using_speak")
async def call_action_gather(
    call_control_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    _body = await request.json()
    return {"data": {"result": "ok"}}


# ─────────────────────────────────────────────────────────────────────────────
# Numbers: available, orders, owned
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/v2/available_phone_numbers")
async def search_available(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    country_code: str = Query(default="US", alias="filter[country_code]"),
    national_destination_code: str | None = Query(
        default=None, alias="filter[national_destination_code]"
    ),
    phone_number_type: str | None = Query(default=None, alias="filter[phone_number_type]"),
    limit: int = Query(default=50, alias="filter[limit]"),
    features_sms: bool | None = Query(default=None, alias="filter[features][sms]"),
    features_mms: bool | None = Query(default=None, alias="filter[features][mms]"),
    features_voice: bool | None = Query(default=None, alias="filter[features][voice]"),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    mapped = {
        "local": "local",
        "toll-free": "tollfree",
        "mobile": "mobile",
    }.get(phone_number_type or "local", "local")
    numbers = get_available_numbers(
        iso_country=country_code,
        number_type=mapped,
        area_code=national_destination_code,
        page_size=limit,
        sms_enabled=features_sms,
        mms_enabled=features_mms,
        voice_enabled=features_voice,
    )
    return fmt.format_available_numbers(numbers)


@router.post("/v2/number_orders")
async def create_number_order(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={"errors": [{"detail": "bad body"}]})
    phone_objs = body.get("phone_numbers", []) or []
    numbers = [p.get("phone_number", "") for p in phone_objs if isinstance(p, dict)]
    numbers = [n for n in numbers if n]
    sid = fmt.new_order_id()
    order = SandboxNumberOrder(
        provider_id=provider.id,
        external_id=sid,
        status="success",
        numbers=numbers,
        raw_request=body,
    )
    db.add(order)
    await db.commit()
    # Register each number as owned
    for e164 in numbers:
        mark_consumed(e164)
        pn = SandboxPhoneNumber(
            provider_id=provider.id,
            external_id=str(__import__("uuid").uuid4()),
            e164=e164,
            iso_country="US",
            number_type="local",
            capabilities={"voice": True, "sms": True, "mms": True, "fax": False},
        )
        db.add(pn)
    await db.commit()
    await db.refresh(order)
    return JSONResponse(status_code=201, content=fmt.format_number_order(order))


@router.get("/v2/number_orders/{order_id}")
async def fetch_number_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxNumberOrder).where(
        SandboxNumberOrder.provider_id == provider.id,
        SandboxNumberOrder.external_id == order_id,
    )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if order is None:
        return JSONResponse(status_code=404, content={"errors": [{"detail": "not found"}]})
    return fmt.format_number_order(order)


@router.get("/v2/phone_numbers")
async def list_owned(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    stmt = (
        select(SandboxPhoneNumber)
        .where(
            SandboxPhoneNumber.provider_id == provider.id,
            SandboxPhoneNumber.released.is_(False),
        )
        .order_by(SandboxPhoneNumber.created_at.desc())
    )
    result = await db.execute(stmt)
    nums = list(result.scalars().all())
    return fmt.format_owned_numbers(nums)


@router.get("/v2/phone_numbers/{phone_number_id}")
async def fetch_owned(
    phone_number_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxPhoneNumber).where(
        SandboxPhoneNumber.provider_id == provider.id,
        SandboxPhoneNumber.external_id == phone_number_id,
    )
    result = await db.execute(stmt)
    pn = result.scalar_one_or_none()
    if pn is None:
        return JSONResponse(status_code=404, content={"errors": [{"detail": "not found"}]})
    return {"data": fmt.format_owned_number(pn)}


@router.patch("/v2/phone_numbers/{phone_number_id}")
async def update_owned(
    phone_number_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxPhoneNumber).where(
        SandboxPhoneNumber.provider_id == provider.id,
        SandboxPhoneNumber.external_id == phone_number_id,
    )
    result = await db.execute(stmt)
    pn = result.scalar_one_or_none()
    if pn is None:
        return JSONResponse(status_code=404, content={"errors": [{"detail": "not found"}]})
    body = await request.json()
    if isinstance(body, dict):
        meta = dict(pn.metadata_json)
        for k in ("messaging_profile_id", "connection_id", "tags"):
            if k in body:
                meta[k] = body[k]
        pn.metadata_json = meta
        await db.commit()
        await db.refresh(pn)
    return {"data": fmt.format_owned_number(pn)}


@router.delete("/v2/phone_numbers/{phone_number_id}", status_code=200)
async def delete_owned(
    phone_number_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxPhoneNumber).where(
        SandboxPhoneNumber.provider_id == provider.id,
        SandboxPhoneNumber.external_id == phone_number_id,
    )
    result = await db.execute(stmt)
    pn = result.scalar_one_or_none()
    if pn is None:
        return JSONResponse(status_code=404, content={"errors": [{"detail": "not found"}]})
    pn.released = True
    release_consumed(pn.e164)
    await db.commit()
    await db.refresh(pn)
    return {"data": fmt.format_owned_number(pn)}


# ─────────────────────────────────────────────────────────────────────────────
# Porting
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/v2/porting_orders")
async def create_port(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={"errors": [{"detail": "bad body"}]})
    numbers_raw = body.get("phone_numbers", []) or body.get("numbers", []) or []
    numbers = [n.get("phone_number", "") for n in numbers_raw if isinstance(n, dict)]
    if not numbers and isinstance(numbers_raw, list):
        numbers = [str(n) for n in numbers_raw]
    sid = fmt.new_port_id()
    port = SandboxPortRequest(
        provider_id=provider.id,
        external_id=sid,
        status="submitted",
        numbers=numbers,
        loa_info={},
        raw_request=body,
    )
    db.add(port)
    await db.commit()

    async def _lifecycle() -> None:
        for s in ["pending-loa", "approved", "foc-scheduled", "ported"]:
            await asyncio.sleep(0.05)
            async with AsyncSessionLocal() as db2:
                stmt2 = select(SandboxPortRequest).where(
                    SandboxPortRequest.provider_id == provider.id,
                    SandboxPortRequest.external_id == sid,
                )
                r = await db2.execute(stmt2)
                p = r.scalar_one_or_none()
                if p is None:
                    return
                p.status = s
                await db2.commit()

    fire_and_forget(_lifecycle())
    await db.refresh(port)
    return JSONResponse(status_code=201, content=fmt.format_port_order(port))


@router.get("/v2/porting_orders/{port_id}")
async def fetch_port(
    port_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxPortRequest).where(
        SandboxPortRequest.provider_id == provider.id,
        SandboxPortRequest.external_id == port_id,
    )
    result = await db.execute(stmt)
    port = result.scalar_one_or_none()
    if port is None:
        return JSONResponse(status_code=404, content={"errors": [{"detail": "not found"}]})
    return fmt.format_port_order(port)


# ─────────────────────────────────────────────────────────────────────────────
# 10DLC Brand / Campaign
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/v2/messaging_tollfree/verification/requests")
async def placeholder_tollfree(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Any:
    _body = await request.json()
    return {"data": {"id": fmt.new_brand_id(), "verified": False}}


@router.post("/v2/brand")
async def create_brand(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={"errors": [{"detail": "bad body"}]})
    sid = fmt.new_brand_id()
    brand = SandboxBrand(
        provider_id=provider.id,
        external_id=sid,
        status="PENDING",
        company_name=body.get("companyName", body.get("displayName", "")),
        ein=body.get("ein"),
        brand_data=body,
        raw_request=body,
    )
    db.add(brand)
    await db.commit()

    async def _approve() -> None:
        await asyncio.sleep(0.1)
        async with AsyncSessionLocal() as db2:
            stmt2 = select(SandboxBrand).where(
                SandboxBrand.provider_id == provider.id,
                SandboxBrand.external_id == sid,
            )
            r = await db2.execute(stmt2)
            b = r.scalar_one_or_none()
            if b is not None:
                b.status = "APPROVED"
                await db2.commit()

    fire_and_forget(_approve())
    await db.refresh(brand)
    return JSONResponse(status_code=201, content=fmt.format_brand(brand))


@router.get("/v2/brand/{brand_id}")
async def fetch_brand(
    brand_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxBrand).where(
        SandboxBrand.provider_id == provider.id,
        SandboxBrand.external_id == brand_id,
    )
    result = await db.execute(stmt)
    brand = result.scalar_one_or_none()
    if brand is None:
        return JSONResponse(status_code=404, content={"errors": [{"detail": "not found"}]})
    return fmt.format_brand(brand)


@router.post("/v2/campaign")
async def create_campaign(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={"errors": [{"detail": "bad body"}]})
    sid = fmt.new_campaign_id()
    brand_id = body.get("brandId")
    brand: SandboxBrand | None = None
    if brand_id:
        stmt = select(SandboxBrand).where(
            SandboxBrand.provider_id == provider.id,
            SandboxBrand.external_id == str(brand_id),
        )
        result = await db.execute(stmt)
        brand = result.scalar_one_or_none()
    samples_raw = [body.get(f"sample{i}") for i in range(1, 6)]
    samples = [s for s in samples_raw if s]
    if not samples and isinstance(body.get("sampleMessages"), list):
        samples = [str(s) for s in body.get("sampleMessages", [])]
    campaign = SandboxCampaign(
        provider_id=provider.id,
        brand_id=brand.id if brand is not None else None,
        external_id=sid,
        status="PENDING",
        use_case=body.get("usecase", "MIXED"),
        description=body.get("description", ""),
        sample_messages=samples,
        raw_request=body,
    )
    db.add(campaign)
    await db.commit()

    async def _approve() -> None:
        await asyncio.sleep(0.1)
        async with AsyncSessionLocal() as db2:
            stmt2 = select(SandboxCampaign).where(
                SandboxCampaign.provider_id == provider.id,
                SandboxCampaign.external_id == sid,
            )
            r = await db2.execute(stmt2)
            c = r.scalar_one_or_none()
            if c is not None:
                c.status = "APPROVED"
                await db2.commit()

    fire_and_forget(_approve())
    await db.refresh(campaign)
    return JSONResponse(status_code=201, content=fmt.format_campaign(campaign))


@router.get("/v2/campaign/{campaign_id}")
async def fetch_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxCampaign).where(
        SandboxCampaign.provider_id == provider.id,
        SandboxCampaign.external_id == campaign_id,
    )
    result = await db.execute(stmt)
    campaign = result.scalar_one_or_none()
    if campaign is None:
        return JSONResponse(status_code=404, content={"errors": [{"detail": "not found"}]})
    return fmt.format_campaign(campaign)


# ─────────────────────────────────────────────────────────────────────────────
# Provider class
# ─────────────────────────────────────────────────────────────────────────────


class TelnyxProvider(BaseSandboxProvider):
    provider_name = "telnyx"

    def get_router(self) -> APIRouter:
        return router

    async def format_outbound_response(self, message: SandboxMessage) -> dict[str, Any]:
        return fmt.format_message(message)

    async def build_webhook_payload(
        self, message: SandboxMessage, event_type: str
    ) -> dict[str, Any]:
        return {
            "data": {
                "event_type": "message.received"
                if message.direction == "inbound"
                else "message.finalized",
                "id": message.external_id,
                "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "payload": fmt.format_message(message)["data"],
                "record_type": "event",
            }
        }

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return "api_key" in credentials

    def get_sandbox_url_hint(self, provider: Any) -> str:
        return "/sandbox/telnyx/v2"
