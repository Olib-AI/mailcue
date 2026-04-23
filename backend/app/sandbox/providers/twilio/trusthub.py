"""Twilio Messaging v1 / TrustHub brand + campaign + profile endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.sandbox.providers.twilio.formatter import format_brand, format_campaign
from app.sandbox.providers.twilio.schemas import (
    BrandRegistrationRequest,
    CustomerProfileRequest,
    UsAppToPersonRequest,
)
from app.sandbox.providers.twilio.service import (
    build_brand_sid,
    build_campaign_sid,
    build_customer_profile_sid,
    create_brand,
    create_campaign,
    extract_basic_auth,
    get_brand,
    get_campaign,
    now_iso,
    resolve_account,
    schedule_brand_approval,
    schedule_campaign_approval,
)

router = APIRouter(prefix="/v1", tags=["Sandbox - Twilio - TrustHub"])


def _unauth() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"code": 20003, "message": "Authenticate", "status": 401},
    )


async def _resolve(db: AsyncSession, authorization: str | None) -> Any:
    creds = extract_basic_auth(authorization)
    if creds is None:
        return None
    user, password = creds
    return await resolve_account(db, user, password)


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


# ── CustomerProfiles (TrustHub) ──────────────────────────────────────────────


@router.post("/CustomerProfiles")
async def create_customer_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    data = await _parse_form(request)
    try:
        body = CustomerProfileRequest(**data)
    except Exception:
        return JSONResponse(
            status_code=400, content={"code": 20001, "message": "Invalid body", "status": 400}
        )
    sid = build_customer_profile_sid()
    return {
        "sid": sid,
        "account_sid": provider.credentials.get("account_sid", ""),
        "policy_sid": body.PolicySid or "RN806dd6cd175f314e1bf9927ba7c1f54c",
        "friendly_name": body.FriendlyName,
        "status": "draft",
        "valid_until": None,
        "email": body.Email,
        "status_callback": body.StatusCallback,
        "date_created": now_iso(),
        "date_updated": now_iso(),
        "url": f"/v1/CustomerProfiles/{sid}",
    }


@router.post("/TrustProducts")
async def create_trust_product(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    data = await _parse_form(request)
    sid = "BU" + build_customer_profile_sid()[2:]
    return {
        "sid": sid,
        "account_sid": provider.credentials.get("account_sid", ""),
        "policy_sid": data.get("PolicySid", "RNb0dce4f4c6c74de4e87b2c3e5f4b8e9a"),
        "friendly_name": data.get("FriendlyName", ""),
        "status": "draft",
        "email": data.get("Email", ""),
        "date_created": now_iso(),
        "date_updated": now_iso(),
        "url": f"/v1/TrustProducts/{sid}",
    }


# ── Brand registration ──────────────────────────────────────────────────────


@router.post("/a2p/BrandRegistrations")
async def create_brand_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    data = await _parse_form(request)
    body = BrandRegistrationRequest(**data)
    sid = build_brand_sid()
    raw = dict(data)
    raw["account_sid"] = provider.credentials.get("account_sid", "")
    brand = await create_brand(
        db,
        provider.id,
        sid,
        brand_type=body.BrandType,
        customer_profile_bundle_sid=body.CustomerProfileBundleSid,
        a2p_profile_bundle_sid=body.A2PProfileBundleSid,
        raw_request=raw,
    )
    schedule_brand_approval(AsyncSessionLocal, provider.id, sid)
    return format_brand(brand)


@router.get("/a2p/BrandRegistrations/{sid}")
async def fetch_brand(
    sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    brand = await get_brand(db, provider.id, sid)
    if brand is None:
        return JSONResponse(
            status_code=404,
            content={"code": 20404, "message": "Brand not found", "status": 404},
        )
    return format_brand(brand)


# ── Campaign (US A2P 10DLC) ─────────────────────────────────────────────────


@router.post("/Services/{messaging_service_sid}/Compliance/Usa2p")
async def create_campaign_endpoint(
    messaging_service_sid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    data = await _parse_form(request)
    body = UsAppToPersonRequest(**data)
    sid = build_campaign_sid()
    raw = dict(data)
    raw["account_sid"] = provider.credentials.get("account_sid", "")
    raw["messaging_service_sid"] = messaging_service_sid
    brand = await get_brand(db, provider.id, body.BrandRegistrationSid)
    campaign = await create_campaign(
        db,
        provider.id,
        sid,
        brand.id if brand is not None else None,
        description=body.Description,
        use_case=body.UsAppToPersonUsecase,
        sample_messages=body.MessageSamples,
        raw_request=raw,
    )
    schedule_campaign_approval(AsyncSessionLocal, provider.id, sid)
    return format_campaign(campaign, messaging_service_sid)


@router.get("/Services/{messaging_service_sid}/Compliance/Usa2p/{sid}")
async def fetch_campaign(
    messaging_service_sid: str,
    sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    campaign = await get_campaign(db, provider.id, sid)
    if campaign is None:
        return JSONResponse(
            status_code=404,
            content={"code": 20404, "message": "Campaign not found", "status": 404},
        )
    return format_campaign(campaign, messaging_service_sid)
