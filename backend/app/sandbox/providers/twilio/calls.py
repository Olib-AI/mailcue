"""Twilio Calls.json endpoints for the sandbox."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.sandbox.providers.twilio.formatter import format_call, format_call_list
from app.sandbox.providers.twilio.schemas import CreateCallRequest, UpdateCallRequest
from app.sandbox.providers.twilio.service import (
    build_call_sid,
    build_call_status_callback,
    create_call,
    extract_basic_auth,
    get_call,
    list_calls,
    resolve_account,
)
from app.sandbox.voice.worker import start_call

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


async def _parse_call_body(request: Request) -> CreateCallRequest:
    ct = (request.headers.get("content-type") or "").lower()
    if ct.startswith("application/x-www-form-urlencoded") or ct.startswith("multipart/form-data"):
        form = await request.form()
        data: dict[str, Any] = {}
        for key in form:
            if key == "StatusCallbackEvent":
                values = form.getlist(key) if hasattr(form, "getlist") else [form.get(key)]
                data[key] = [str(v) for v in values if v]
            else:
                data[key] = str(form.get(key, ""))
        return CreateCallRequest(**data)
    body = await request.json()
    if isinstance(body, dict):
        return CreateCallRequest(**body)
    return CreateCallRequest(To="", From="")


async def _parse_update_body(request: Request) -> UpdateCallRequest:
    ct = (request.headers.get("content-type") or "").lower()
    if ct.startswith("application/x-www-form-urlencoded") or ct.startswith("multipart/form-data"):
        form = await request.form()
        return UpdateCallRequest(**{k: str(v) for k, v in form.items()})
    body = await request.json()
    if isinstance(body, dict):
        return UpdateCallRequest(**body)
    return UpdateCallRequest()


@router.post("/{account_sid}/Calls.json")
async def create_call_endpoint(
    account_sid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_sid, authorization)
    if provider is None:
        return _unauth()
    body = await _parse_call_body(request)
    if not body.To or not body.From:
        return JSONResponse(
            status_code=400,
            content={
                "code": 21205,
                "message": "'To' and 'From' are required",
                "status": 400,
            },
        )

    sid = build_call_sid()
    call = await create_call(
        db,
        provider.id,
        sid,
        from_number=body.From,
        to_number=body.To,
        answer_url=body.Url,
        answer_method=body.Method or "POST",
        status_callback=body.StatusCallback,
        status_callback_method=body.StatusCallbackMethod or "POST",
        record=bool(body.Record),
        raw_request=body.model_dump(exclude_none=True),
    )

    async def _status_cb(status: str, call_snapshot: Any, extra: dict[str, Any]) -> None:
        async with AsyncSessionLocal() as db2:
            fresh = await get_call(db2, provider.id, sid)
            if fresh is not None:
                await build_call_status_callback(db2, fresh, account_sid, status, extra)

    start_call(
        call_id=call.id,
        provider_type="twilio",
        seed_digits=provider.credentials.get("sandbox_seed_digits", "1"),
        seed_speech=provider.credentials.get("sandbox_seed_speech", "yes"),
        status_cb=_status_cb,
    )

    return format_call(call, account_sid)


@router.get("/{account_sid}/Calls.json")
async def list_calls_endpoint(
    account_sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    page_size: int = Query(default=50, alias="PageSize"),
) -> Any:
    provider = await _resolve(db, account_sid, authorization)
    if provider is None:
        return _unauth()
    calls = await list_calls(db, provider.id, limit=page_size)
    return format_call_list(calls, account_sid)


@router.get("/{account_sid}/Calls/{call_sid}.json")
async def get_call_endpoint(
    account_sid: str,
    call_sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_sid, authorization)
    if provider is None:
        return _unauth()
    call = await get_call(db, provider.id, call_sid)
    if call is None:
        return JSONResponse(
            status_code=404,
            content={
                "code": 20404,
                "message": f"The requested resource /Calls/{call_sid}.json was not found",
                "status": 404,
            },
        )
    return format_call(call, account_sid)


@router.post("/{account_sid}/Calls/{call_sid}.json")
async def update_call_endpoint(
    account_sid: str,
    call_sid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_sid, authorization)
    if provider is None:
        return _unauth()
    call = await get_call(db, provider.id, call_sid)
    if call is None:
        return JSONResponse(
            status_code=404,
            content={"code": 20404, "message": "Call not found", "status": 404},
        )
    body = await _parse_update_body(request)
    if body.Status in {"canceled", "completed"}:
        call.status = "canceled" if body.Status == "canceled" else "completed"
    if body.Url is not None:
        call.answer_url = body.Url
    if body.Method is not None:
        call.answer_method = body.Method
    await db.commit()
    await db.refresh(call)
    return format_call(call, account_sid)
