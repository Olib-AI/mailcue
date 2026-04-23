"""Twilio AvailablePhoneNumbers + IncomingPhoneNumbers endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.sandbox.providers.twilio.formatter import (
    format_available_number_list,
    format_incoming_number,
    format_incoming_number_list,
)
from app.sandbox.providers.twilio.schemas import (
    PurchaseNumberRequest,
    UpdateIncomingNumberRequest,
)
from app.sandbox.providers.twilio.service import (
    build_incoming_number_sid,
    create_incoming_number,
    extract_basic_auth,
    get_incoming_number,
    list_incoming_numbers,
    resolve_account,
)
from app.sandbox.seeds.available_numbers import (
    get_available_numbers,
    mark_consumed,
    release_consumed,
)

router = APIRouter()


async def _resolve(db: AsyncSession, account_sid: str, authorization: str | None) -> Any:
    creds = extract_basic_auth(authorization)
    if creds is None:
        return None
    user, password = creds
    if user != account_sid:
        return None
    return await resolve_account(db, account_sid, password)


def _unauth() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"code": 20003, "message": "Authenticate", "status": 401},
    )


_TYPE_MAP: dict[str, str] = {
    "Local": "local",
    "Mobile": "mobile",
    "TollFree": "tollfree",
}


@router.get(
    "/{account_sid}/AvailablePhoneNumbers/{country}/{number_type}.json",
)
async def search_available_numbers(
    account_sid: str,
    country: str,
    number_type: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    area_code: str | None = Query(default=None, alias="AreaCode"),
    contains: str | None = Query(default=None, alias="Contains"),
    page_size: int = Query(default=50, alias="PageSize"),
    sms_enabled: bool | None = Query(default=None, alias="SmsEnabled"),
    mms_enabled: bool | None = Query(default=None, alias="MmsEnabled"),
    voice_enabled: bool | None = Query(default=None, alias="VoiceEnabled"),
) -> Any:
    provider = await _resolve(db, account_sid, authorization)
    if provider is None:
        return _unauth()
    mapped_type = _TYPE_MAP.get(number_type, number_type.lower())
    numbers = get_available_numbers(
        iso_country=country,
        number_type=mapped_type,
        area_code=area_code,
        contains=contains,
        page_size=page_size,
        sms_enabled=sms_enabled,
        mms_enabled=mms_enabled,
        voice_enabled=voice_enabled,
    )
    return format_available_number_list(numbers, account_sid, country, number_type)


async def _parse_purchase_body(request: Request) -> PurchaseNumberRequest:
    ct = (request.headers.get("content-type") or "").lower()
    if ct.startswith("application/x-www-form-urlencoded") or ct.startswith("multipart/form-data"):
        form = await request.form()
        return PurchaseNumberRequest(**{k: str(v) for k, v in form.items()})
    body = await request.json()
    if isinstance(body, dict):
        return PurchaseNumberRequest(**body)
    return PurchaseNumberRequest()


async def _parse_update_body(request: Request) -> UpdateIncomingNumberRequest:
    ct = (request.headers.get("content-type") or "").lower()
    if ct.startswith("application/x-www-form-urlencoded") or ct.startswith("multipart/form-data"):
        form = await request.form()
        return UpdateIncomingNumberRequest(**{k: str(v) for k, v in form.items()})
    body = await request.json()
    if isinstance(body, dict):
        return UpdateIncomingNumberRequest(**body)
    return UpdateIncomingNumberRequest()


@router.post("/{account_sid}/IncomingPhoneNumbers.json")
async def purchase_number(
    account_sid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_sid, authorization)
    if provider is None:
        return _unauth()
    body = await _parse_purchase_body(request)
    e164 = body.PhoneNumber
    locality: str | None = None
    region: str | None = None
    iso_country = "US"
    number_type = "local"
    capabilities: dict[str, bool] = {"voice": True, "sms": True, "mms": True, "fax": False}

    if e164 is None and body.AreaCode is not None:
        matches = get_available_numbers(area_code=body.AreaCode, page_size=1)
        if not matches:
            return JSONResponse(
                status_code=400,
                content={
                    "code": 21422,
                    "message": "No phone numbers available in that area code",
                    "status": 400,
                },
            )
        entry = matches[0]
        e164 = entry.e164
        iso_country = entry.iso_country
        number_type = entry.number_type
        locality = entry.locality
        region = entry.region
        capabilities = dict(entry.capabilities)
    else:
        # Look up metadata if this number is in the pool
        for entry in get_available_numbers(iso_country="US", page_size=500):
            if entry.e164 == e164:
                iso_country = entry.iso_country
                number_type = entry.number_type
                locality = entry.locality
                region = entry.region
                capabilities = dict(entry.capabilities)
                break

    if e164 is None:
        return JSONResponse(
            status_code=400,
            content={
                "code": 21421,
                "message": "PhoneNumber or AreaCode required",
                "status": 400,
            },
        )

    mark_consumed(e164)
    sid = build_incoming_number_sid()
    pn = await create_incoming_number(
        db,
        provider.id,
        sid,
        e164=e164,
        friendly_name=body.FriendlyName or e164,
        iso_country=iso_country,
        number_type=number_type,
        locality=locality,
        region=region,
        capabilities=capabilities,
        sms_url=body.SmsUrl,
        voice_url=body.VoiceUrl,
        status_callback=body.StatusCallback,
        raw_request=body.model_dump(exclude_none=True),
    )
    return format_incoming_number(pn, account_sid)


@router.get("/{account_sid}/IncomingPhoneNumbers.json")
async def list_incoming(
    account_sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_sid, authorization)
    if provider is None:
        return _unauth()
    nums = await list_incoming_numbers(db, provider.id)
    return format_incoming_number_list(nums, account_sid)


@router.get("/{account_sid}/IncomingPhoneNumbers/{sid}.json")
async def get_incoming(
    account_sid: str,
    sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_sid, authorization)
    if provider is None:
        return _unauth()
    pn = await get_incoming_number(db, provider.id, sid)
    if pn is None:
        return JSONResponse(
            status_code=404,
            content={"code": 20404, "message": "Resource not found", "status": 404},
        )
    return format_incoming_number(pn, account_sid)


@router.post("/{account_sid}/IncomingPhoneNumbers/{sid}.json")
async def update_incoming(
    account_sid: str,
    sid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_sid, authorization)
    if provider is None:
        return _unauth()
    pn = await get_incoming_number(db, provider.id, sid)
    if pn is None:
        return JSONResponse(
            status_code=404,
            content={"code": 20404, "message": "Resource not found", "status": 404},
        )
    body = await _parse_update_body(request)
    if body.FriendlyName is not None:
        pn.metadata_json = {**pn.metadata_json, "friendly_name": body.FriendlyName}
    if body.SmsUrl is not None:
        pn.sms_url = body.SmsUrl
    if body.SmsMethod is not None:
        pn.sms_method = body.SmsMethod
    if body.VoiceUrl is not None:
        pn.voice_url = body.VoiceUrl
    if body.VoiceMethod is not None:
        pn.voice_method = body.VoiceMethod
    if body.StatusCallback is not None:
        pn.status_callback = body.StatusCallback
    await db.commit()
    await db.refresh(pn)
    return format_incoming_number(pn, account_sid)


@router.delete(
    "/{account_sid}/IncomingPhoneNumbers/{sid}.json", status_code=204, response_model=None
)
async def release_incoming(
    account_sid: str,
    sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    from fastapi import Response

    provider = await _resolve(db, account_sid, authorization)
    if provider is None:
        return _unauth()
    pn = await get_incoming_number(db, provider.id, sid)
    if pn is None:
        return JSONResponse(
            status_code=404,
            content={"code": 20404, "message": "Resource not found", "status": 404},
        )
    pn.released = True
    release_consumed(pn.e164)
    await db.commit()
    return Response(status_code=204)
