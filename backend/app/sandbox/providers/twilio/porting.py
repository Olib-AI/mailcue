"""Twilio Numbers v1 Porting endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.sandbox.providers.twilio.formatter import format_port_order
from app.sandbox.providers.twilio.schemas import PortingOrderRequest
from app.sandbox.providers.twilio.service import (
    build_port_sid,
    create_port_order,
    extract_basic_auth,
    get_port_order,
    resolve_account,
    schedule_port_lifecycle,
)

router = APIRouter(prefix="/v1/Porting", tags=["Sandbox - Twilio - Porting"])


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


async def _parse_body(request: Request) -> PortingOrderRequest:
    ct = (request.headers.get("content-type") or "").lower()
    if ct.startswith("application/x-www-form-urlencoded") or ct.startswith("multipart/form-data"):
        form = await request.form()
        raw: dict[str, Any] = {}
        for key in form:
            vals = form.getlist(key) if hasattr(form, "getlist") else [form.get(key)]
            if key in {"phone_numbers", "notification_emails"}:
                raw[key] = [str(v) for v in vals if v]
            else:
                raw[key] = str(form.get(key, ""))
        return PortingOrderRequest(**raw)
    body = await request.json()
    if isinstance(body, dict):
        return PortingOrderRequest(**body)
    return PortingOrderRequest()


@router.post("/Orders")
async def create_port(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    body = await _parse_body(request)
    sid = build_port_sid()
    raw = body.model_dump(exclude_none=True)
    raw["account_sid"] = provider.credentials.get("account_sid", "")
    order = await create_port_order(
        db,
        provider.id,
        sid,
        numbers=body.phone_numbers,
        loa_info=body.loa_info,
        raw_request=raw,
    )
    schedule_port_lifecycle(
        AsyncSessionLocal,
        provider.id,
        sid,
        ["pending-loa", "approved", "foc-scheduled", "completed"],
    )
    return format_port_order(order)


@router.get("/Orders/{order_sid}")
async def fetch_port(
    order_sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    order = await get_port_order(db, provider.id, order_sid)
    if order is None:
        return JSONResponse(
            status_code=404,
            content={"code": 20404, "message": "Port order not found", "status": 404},
        )
    return format_port_order(order)


@router.post("/Orders/{order_sid}")
async def cancel_port(
    order_sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, authorization)
    if provider is None:
        return _unauth()
    order = await get_port_order(db, provider.id, order_sid)
    if order is None:
        return JSONResponse(
            status_code=404,
            content={"code": 20404, "message": "Port order not found", "status": 404},
        )
    order.status = "canceled"
    order.cancelled = True
    await db.commit()
    await db.refresh(order)
    return format_port_order(order)
