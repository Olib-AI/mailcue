"""Plivo sandbox router: Messages, Calls, Numbers, 10DLC, Port."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.sandbox.models import (
    SandboxBrand,
    SandboxCall,
    SandboxCampaign,
    SandboxMessage,
    SandboxPhoneNumber,
    SandboxPortRequest,
)
from app.sandbox.providers.base import BaseSandboxProvider
from app.sandbox.providers.plivo import formatter as fmt
from app.sandbox.providers.plivo.service import extract_basic_auth, resolve_account
from app.sandbox.seeds.available_numbers import (
    get_available_numbers,
    mark_consumed,
    release_consumed,
)
from app.sandbox.service import (
    get_messages,
    get_or_create_conversation,
    store_message,
    update_raw_response,
)
from app.sandbox.voice.worker import start_call
from app.sandbox.webhook_raw import fire_and_forget, post_form

logger = logging.getLogger("mailcue.sandbox.plivo")

router = APIRouter(prefix="/sandbox/plivo", tags=["Sandbox - Plivo"])


def _unauth() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "api_id": "mailcue-sandbox",
            "error": "authentication failed",
        },
    )


async def _resolve(db: AsyncSession, auth_id: str, authorization: str | None) -> Any:
    creds = extract_basic_auth(authorization)
    if creds is None:
        return None
    user, pw = creds
    if user != auth_id:
        return None
    return await resolve_account(db, auth_id, pw)


async def _parse_form(request: Request) -> dict[str, Any]:
    ct = (request.headers.get("content-type") or "").lower()
    if ct.startswith("application/x-www-form-urlencoded") or ct.startswith("multipart/form-data"):
        form = await request.form()
        out: dict[str, Any] = {}
        for key in form:
            vals = form.getlist(key) if hasattr(form, "getlist") else [form.get(key)]
            if len(vals) > 1:
                out[key] = [str(v) for v in vals if v]
            else:
                out[key] = str(form.get(key, ""))
        return out
    body = await request.json()
    return body if isinstance(body, dict) else {}


# ─────────────────────────────────────────────────────────────────────────────
# Messages
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/v1/Account/{auth_id}/Message/")
async def send_message(
    auth_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    data = await _parse_form(request)
    src = data.get("src") or data.get("from")
    dst_raw = data.get("dst") or data.get("to") or ""
    dst_list = (
        [d for d in str(dst_raw).split("<") if d]
        if isinstance(dst_raw, str) and "<" in dst_raw
        else (dst_raw if isinstance(dst_raw, list) else [dst_raw])
    )
    text = data.get("text", "")
    media_raw = data.get("media_urls") or data.get("media")
    media: list[str]
    if isinstance(media_raw, list):
        media = [str(v) for v in media_raw]
    elif isinstance(media_raw, str) and media_raw:
        media = [media_raw]
    else:
        media = []

    msg_uuid = fmt.new_message_uuid()
    to_single = dst_list[0] if dst_list else ""
    conv_ext = f"{src}->{to_single}"
    conv = await get_or_create_conversation(db, provider.id, conv_ext, conv_ext, "sms")
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        str(src or ""),
        str(text),
        conversation_id=conv.id,
        content_type="mms" if media else "sms",
        external_id=msg_uuid,
        raw_request=data,
        metadata={
            "from": str(src or ""),
            "to": dst_list if dst_list else str(dst_raw),
            "media_urls": media,
            "auth_id": auth_id,
        },
    )
    response = fmt.format_send_message_response(msg, auth_id)
    await update_raw_response(db, msg, response)
    return JSONResponse(status_code=202, content=response)


@router.get("/v1/Account/{auth_id}/Message/")
async def list_messages(
    auth_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    limit: int = Query(default=20),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    messages, _ = await get_messages(db, provider.id, limit=limit)
    return fmt.format_message_list(messages, auth_id)


@router.get("/v1/Account/{auth_id}/Message/{message_uuid}/")
async def fetch_message(
    auth_id: str,
    message_uuid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxMessage).where(
        SandboxMessage.provider_id == provider.id,
        SandboxMessage.external_id == message_uuid,
    )
    result = await db.execute(stmt)
    msg = result.scalar_one_or_none()
    if msg is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return fmt.format_message(msg, auth_id)


# ─────────────────────────────────────────────────────────────────────────────
# Calls
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/v1/Account/{auth_id}/Call/")
async def create_call(
    auth_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    data = await _parse_form(request)
    src = str(data.get("from", ""))
    to_raw = data.get("to", "")
    to = to_raw if isinstance(to_raw, str) else str(to_raw[0] if to_raw else "")
    answer_url = data.get("answer_url")
    answer_method = str(data.get("answer_method", "POST"))
    hangup_url = data.get("hangup_url")

    call_uuid = fmt.new_call_uuid()
    call = SandboxCall(
        provider_id=provider.id,
        external_id=call_uuid,
        direction="outbound",
        from_number=src,
        to_number=to,
        status="queued",
        answer_url=answer_url if isinstance(answer_url, str) else None,
        answer_method=answer_method,
        status_callback=hangup_url if isinstance(hangup_url, str) else None,
        raw_request=data,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)

    async def _cb(status: str, call_snap: Any, extra: dict[str, Any]) -> None:
        if call_snap.status_callback is None:
            return
        event_map = {
            "initiated": "initiate",
            "ringing": "ringing",
            "answered": "in-progress",
            "completed": "completed",
            "failed": "failed",
        }
        status_label = event_map.get(status, status)
        payload = {
            "CallUUID": call_snap.external_id,
            "From": call_snap.from_number,
            "To": call_snap.to_number,
            "Direction": "outbound",
            "CallStatus": status_label,
            "Event": "Hangup" if status == "completed" else "Answered",
        }
        if status == "completed":
            payload["Duration"] = call_snap.duration_seconds
        # Plivo status callbacks carry X-Plivo-Signature-V3 + nonce so
        # fase's RequestValidator accepts them without sandbox-mode
        # exceptions.  Signature is over URL + nonce + sha256(body).
        from app.sandbox.signers import make_plivo_v3_signer

        signer = make_plivo_v3_signer(
            auth_token=str(provider.credentials.get("auth_token") or ""),
            url=call_snap.status_callback,
        )
        await post_form(call_snap.status_callback, payload, signer=signer)

    start_call(
        call_id=call.id,
        provider_type="plivo",
        seed_digits=provider.credentials.get("sandbox_seed_digits", "1"),
        seed_speech=provider.credentials.get("sandbox_seed_speech", "yes"),
        status_cb=_cb,
    )

    return JSONResponse(
        status_code=201,
        content={
            "api_id": str(call_uuid),
            "message": "call fired",
            "request_uuid": call_uuid,
        },
    )


@router.get("/v1/Account/{auth_id}/Call/")
async def list_calls(
    auth_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    limit: int = Query(default=20),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    stmt = (
        select(SandboxCall)
        .where(SandboxCall.provider_id == provider.id)
        .order_by(SandboxCall.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    calls = list(result.scalars().all())
    return fmt.format_call_list(calls, auth_id)


@router.get("/v1/Account/{auth_id}/Call/{call_uuid}/")
async def fetch_call(
    auth_id: str,
    call_uuid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxCall).where(
        SandboxCall.provider_id == provider.id,
        SandboxCall.external_id == call_uuid,
    )
    result = await db.execute(stmt)
    call = result.scalar_one_or_none()
    if call is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return fmt.format_call(call, auth_id)


# ─────────────────────────────────────────────────────────────────────────────
# Numbers
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/v1/Account/{auth_id}/PhoneNumber/")
async def search_numbers(
    auth_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    country_iso: str = Query(default="US"),
    type_: str | None = Query(default=None, alias="type"),
    pattern: str | None = Query(default=None),
    region: str | None = Query(default=None),
    services: str | None = Query(default=None),
    limit: int = Query(default=20),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    sms_only = (
        services is not None and "sms" in services.lower() and "voice" not in services.lower()
    )
    voice_only = (
        services is not None and "voice" in services.lower() and "sms" not in services.lower()
    )
    numbers = get_available_numbers(
        iso_country=country_iso,
        number_type=type_,
        contains=pattern,
        page_size=limit,
        sms_enabled=True if sms_only else None,
        voice_enabled=True if voice_only else None,
    )
    return fmt.format_available_number_list(numbers)


@router.post("/v1/Account/{auth_id}/PhoneNumber/{number}/")
async def buy_number(
    auth_id: str,
    number: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    e164 = "+" + number.lstrip("+")
    # Look up seed metadata
    iso = "US"
    ntype = "local"
    caps = {"voice": True, "sms": True, "mms": True, "fax": False}
    locality: str | None = None
    region: str | None = None
    for entry in get_available_numbers(iso_country="US", page_size=500):
        if entry.e164 == e164:
            iso, ntype = entry.iso_country, entry.number_type
            caps = dict(entry.capabilities)
            locality, region = entry.locality, entry.region
            break
    mark_consumed(e164)
    pn = SandboxPhoneNumber(
        provider_id=provider.id,
        external_id="PN-" + e164.lstrip("+"),
        e164=e164,
        iso_country=iso,
        number_type=ntype,
        locality=locality,
        region=region,
        capabilities=caps,
    )
    db.add(pn)
    await db.commit()
    await db.refresh(pn)
    return JSONResponse(
        status_code=201,
        content={
            "api_id": str(pn.id),
            "message": "created",
            "number": e164.lstrip("+"),
            "status": "success",
        },
    )


@router.get("/v1/Account/{auth_id}/Number/")
async def list_owned(
    auth_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
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
    return fmt.format_owned_number_list(nums, auth_id)


@router.delete("/v1/Account/{auth_id}/Number/{number}/", status_code=204, response_model=None)
async def release_owned(
    auth_id: str,
    number: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    e164 = "+" + number.lstrip("+")
    stmt = select(SandboxPhoneNumber).where(
        SandboxPhoneNumber.provider_id == provider.id,
        SandboxPhoneNumber.e164 == e164,
    )
    result = await db.execute(stmt)
    pn = result.scalar_one_or_none()
    if pn is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    pn.released = True
    release_consumed(e164)
    await db.commit()
    return Response(status_code=204)


# ─────────────────────────────────────────────────────────────────────────────
# 10DLC brand + campaign
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/v1/Account/{auth_id}/10dlc/Brand/")
async def create_brand(
    auth_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    data = await _parse_form(request)
    sid = fmt.new_brand_id()
    brand = SandboxBrand(
        provider_id=provider.id,
        external_id=sid,
        status="PENDING",
        company_name=str(data.get("brand_name", data.get("company_name", ""))),
        ein=data.get("ein"),
        brand_data=data,
        raw_request=data,
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


@router.get("/v1/Account/{auth_id}/10dlc/Brand/{brand_id}/")
async def fetch_brand(
    auth_id: str,
    brand_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxBrand).where(
        SandboxBrand.provider_id == provider.id,
        SandboxBrand.external_id == brand_id,
    )
    result = await db.execute(stmt)
    brand = result.scalar_one_or_none()
    if brand is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return fmt.format_brand(brand)


@router.post("/v1/Account/{auth_id}/10dlc/Campaign/")
async def create_campaign(
    auth_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    data = await _parse_form(request)
    sid = fmt.new_campaign_id()
    brand_id = data.get("brand_id")
    brand: SandboxBrand | None = None
    if brand_id:
        stmt = select(SandboxBrand).where(
            SandboxBrand.provider_id == provider.id,
            SandboxBrand.external_id == str(brand_id),
        )
        result = await db.execute(stmt)
        brand = result.scalar_one_or_none()
    sample_raw = data.get("sample_messages") or []
    samples = (
        [str(v) for v in sample_raw]
        if isinstance(sample_raw, list)
        else [str(sample_raw)]
        if sample_raw
        else []
    )
    campaign = SandboxCampaign(
        provider_id=provider.id,
        brand_id=brand.id if brand is not None else None,
        external_id=sid,
        status="PENDING",
        use_case=str(data.get("usecase", "MIXED")),
        description=str(data.get("description", "")),
        sample_messages=samples,
        raw_request=data,
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


@router.get("/v1/Account/{auth_id}/10dlc/Campaign/{campaign_id}/")
async def fetch_campaign(
    auth_id: str,
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxCampaign).where(
        SandboxCampaign.provider_id == provider.id,
        SandboxCampaign.external_id == campaign_id,
    )
    result = await db.execute(stmt)
    campaign = result.scalar_one_or_none()
    if campaign is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return fmt.format_campaign(campaign)


# ─────────────────────────────────────────────────────────────────────────────
# Port
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/v1/Account/{auth_id}/Port/")
async def create_port(
    auth_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    data = await _parse_form(request)
    phones_raw = data.get("phone_numbers") or data.get("numbers") or []
    numbers = [str(v) for v in phones_raw] if isinstance(phones_raw, list) else [str(phones_raw)]
    sid = fmt.new_port_id()
    port = SandboxPortRequest(
        provider_id=provider.id,
        external_id=sid,
        status="SUBMITTED",
        numbers=numbers,
        loa_info={"type": str(data.get("loa_type", "CARRIER"))},
        raw_request=data,
    )
    db.add(port)
    await db.commit()

    async def _lifecycle() -> None:
        for s in ["APPROVED", "FOC_SCHEDULED", "COMPLETED"]:
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
    return JSONResponse(status_code=201, content=fmt.format_port_request(port))


@router.get("/v1/Account/{auth_id}/Port/{port_id}/")
async def fetch_port(
    auth_id: str,
    port_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxPortRequest).where(
        SandboxPortRequest.provider_id == provider.id,
        SandboxPortRequest.external_id == port_id,
    )
    result = await db.execute(stmt)
    port = result.scalar_one_or_none()
    if port is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return fmt.format_port_request(port)


@router.delete("/v1/Account/{auth_id}/Port/{port_id}/", status_code=204, response_model=None)
async def cancel_port(
    auth_id: str,
    port_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, auth_id, authorization)
    if provider is None:
        return _unauth()
    stmt = select(SandboxPortRequest).where(
        SandboxPortRequest.provider_id == provider.id,
        SandboxPortRequest.external_id == port_id,
    )
    result = await db.execute(stmt)
    port = result.scalar_one_or_none()
    if port is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    port.cancelled = True
    port.status = "CANCELLED"
    await db.commit()
    return Response(status_code=204)


# ─────────────────────────────────────────────────────────────────────────────
# Provider class
# ─────────────────────────────────────────────────────────────────────────────


class PlivoProvider(BaseSandboxProvider):
    provider_name = "plivo"

    def get_router(self) -> APIRouter:
        return router

    async def format_outbound_response(self, message: SandboxMessage) -> dict[str, Any]:
        return fmt.format_send_message_response(message, message.metadata_json.get("auth_id", ""))

    async def build_webhook_payload(
        self, message: SandboxMessage, event_type: str
    ) -> dict[str, Any]:
        to_raw = message.metadata_json.get("to")
        to = to_raw[0] if isinstance(to_raw, list) and to_raw else (to_raw or "")
        return {
            "MessageUUID": message.external_id,
            "From": message.metadata_json.get("from", message.sender),
            "To": to,
            "Text": message.content or "",
            "Type": "mms" if message.metadata_json.get("media_urls") else "sms",
            "Status": event_type,
            "Direction": "outbound" if message.direction == "outbound" else "inbound",
        }

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return "auth_id" in credentials and "auth_token" in credentials

    def get_sandbox_url_hint(self, provider: Any) -> str:
        auth_id = provider.credentials.get("auth_id", "{auth_id}")
        return f"/sandbox/plivo/v1/Account/{auth_id}/Message/"
