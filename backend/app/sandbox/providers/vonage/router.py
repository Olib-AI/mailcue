"""Vonage sandbox router: Messages API v1, Voice API v1, Numbers."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.sandbox.models import SandboxMessage, SandboxPhoneNumber
from app.sandbox.providers.base import BaseSandboxProvider
from app.sandbox.providers.vonage import formatter as fmt
from app.sandbox.providers.vonage.service import (
    list_calls_for,
    list_owned_numbers,
    resolve_by_api_key,
    resolve_messages_bearer,
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
from app.sandbox.webhook_raw import post_json

logger = logging.getLogger("mailcue.sandbox.vonage")

router = APIRouter(prefix="/sandbox/vonage", tags=["Sandbox - Vonage"])


def _unauth_messages() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "type": "https://developer.nexmo.com/api-errors#unauthorized",
            "title": "Unauthorized",
            "detail": "You did not provide correct credentials.",
            "instance": "mailcue-sandbox",
        },
    )


def _unauth_voice() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "type": "UNAUTHORIZED",
            "error_title": "Unauthorized",
        },
    )


async def _resolve_messages(db: AsyncSession, authorization: str | None) -> Any:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return await resolve_messages_bearer(db, authorization.removeprefix("Bearer ").strip())


async def _resolve_voice(db: AsyncSession, authorization: str | None) -> Any:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return await resolve_messages_bearer(db, authorization.removeprefix("Bearer ").strip())


async def _resolve_numbers(db: AsyncSession, api_key: str | None, api_secret: str | None) -> Any:
    if not api_key or not api_secret:
        return None
    return await resolve_by_api_key(db, api_key, api_secret)


# ─────────────────────────────────────────────────────────────────────────────
# Messages API v1
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/v1/messages")
async def send_message(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve_messages(db, authorization)
    if provider is None:
        return _unauth_messages()
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(
            status_code=422,
            content={"title": "Invalid request body", "detail": "body must be JSON object"},
        )
    message_type = body.get("message_type", "text")
    channel = body.get("channel", "sms")
    to = body.get("to") or {}
    frm = body.get("from") or {}
    to_number = to.get("number", "")
    from_number = frm.get("number", "")
    text = body.get("text", "")

    media_urls: list[str] = []
    if message_type in {"image", "video", "audio", "file"}:
        resource = body.get(message_type) or {}
        url = resource.get("url")
        if url:
            media_urls.append(str(url))

    msg_id = fmt.new_message_uuid()
    conv_ext = f"{from_number}->{to_number}"
    conv = await get_or_create_conversation(db, provider.id, conv_ext, conv_ext, channel)
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        from_number,
        text,
        conversation_id=conv.id,
        content_type=message_type,
        external_id=msg_id,
        raw_request=body,
        metadata={
            "from": from_number,
            "to": to_number,
            "channel": channel,
            "message_type": message_type,
            "media_urls": media_urls,
        },
    )
    response = fmt.format_message_send_response(msg)
    await update_raw_response(db, msg, response)
    return JSONResponse(status_code=202, content=response)


# ─────────────────────────────────────────────────────────────────────────────
# Voice API v1
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/v1/calls")
async def create_call(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve_voice(db, authorization)
    if provider is None:
        return _unauth_voice()
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"detail": "Invalid body"})

    from app.sandbox.providers.vonage.service import resolve_messages_bearer  # noqa: F401

    to_list = body.get("to") or []
    to_number = to_list[0].get("number", "") if to_list and isinstance(to_list[0], dict) else ""
    frm = body.get("from") or {}
    from_number = frm.get("number", "")
    ncco = body.get("ncco")
    answer_url_list = body.get("answer_url") or []
    answer_url = (
        answer_url_list[0] if isinstance(answer_url_list, list) and answer_url_list else None
    )

    # Vonage can provide either inline ncco or an answer_url. For inline ncco
    # we persist it so the worker can replay when it doesn't fetch anything.
    from app.sandbox.models import SandboxCall

    call_uuid = fmt.new_call_uuid()
    call = SandboxCall(
        provider_id=provider.id,
        external_id=call_uuid,
        direction="outbound",
        from_number=from_number,
        to_number=to_number,
        status="started",
        answer_url=answer_url,
        answer_method=body.get("answer_method", "GET"),
        status_callback=(body.get("event_url") or [None])[0]
        if isinstance(body.get("event_url"), list)
        else body.get("event_url"),
        status_callback_method=body.get("event_method", "POST"),
        raw_request=body,
        metadata_json={
            "ncco": ncco,
            "application_id": provider.credentials.get("application_id", ""),
        },
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)

    # If ncco inline, interpret directly without fetching an answer_url
    async def _status_cb(status: str, call_snap: Any, extra: dict[str, Any]) -> None:
        event_url = call_snap.status_callback
        if not event_url:
            return
        status_map = {
            "initiated": "started",
            "ringing": "ringing",
            "answered": "answered",
            "completed": "completed",
            "failed": "failed",
            "canceled": "cancelled",
        }
        vonage_status = status_map.get(status, status)
        payload = {
            "from": call_snap.from_number,
            "to": call_snap.to_number,
            "uuid": call_snap.external_id,
            "conversation_uuid": call_snap.metadata_json.get(
                "conversation_uuid", call_snap.external_id
            ),
            "status": vonage_status,
            "direction": "outbound",
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        if status == "completed":
            payload["duration"] = str(call_snap.duration_seconds)
            payload["start_time"] = (
                call_snap.answered_at.isoformat().replace("+00:00", "Z")
                if call_snap.answered_at
                else None
            )
            payload["end_time"] = (
                call_snap.ended_at.isoformat().replace("+00:00", "Z")
                if call_snap.ended_at
                else None
            )
        # Vonage Voice/Messages webhooks use Bearer-JWT signed by the
        # Application's private key.  If the credentials don't carry a
        # key we leave the request unsigned (matches Vonage behaviour
        # for applications without a key pair configured).
        signer = None
        app_id = provider.credentials.get("application_id")
        priv_pem = provider.credentials.get("private_key")
        if app_id and priv_pem:
            from app.sandbox.signers import make_vonage_messages_signer

            signer = make_vonage_messages_signer(
                application_id=str(app_id),
                private_key_pem=str(priv_pem),
            )
        await post_json(event_url, payload, signer=signer)

    # Pre-set the call's answer-url content with ncco if inline ncco provided
    if ncco is not None and answer_url is None:
        # Emulate an embedded NCCO by writing a tiny local endpoint?
        # Instead: briefly set the raw request body so worker can parse it
        call.raw_request = {**call.raw_request, "__inline_ncco__": json.dumps(ncco)}
        await db.commit()

    start_call(
        call_id=call.id,
        provider_type="vonage",
        seed_digits=provider.credentials.get("sandbox_seed_digits", "1"),
        seed_speech=provider.credentials.get("sandbox_seed_speech", "yes"),
        status_cb=_status_cb,
    )

    return JSONResponse(
        status_code=201,
        content={
            "uuid": call_uuid,
            "status": "started",
            "direction": "outbound",
            "conversation_uuid": call.metadata_json.get("conversation_uuid", call_uuid),
        },
    )


@router.get("/v1/calls/{call_uuid}")
async def fetch_call(
    call_uuid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    from sqlalchemy import select

    from app.sandbox.models import SandboxCall

    provider = await _resolve_voice(db, authorization)
    if provider is None:
        return _unauth_voice()
    stmt = select(SandboxCall).where(
        SandboxCall.provider_id == provider.id,
        SandboxCall.external_id == call_uuid,
    )
    result = await db.execute(stmt)
    call = result.scalar_one_or_none()
    if call is None:
        return JSONResponse(status_code=404, content={"detail": "Call not found"})
    return fmt.format_call(call)


@router.get("/v1/calls")
async def list_calls(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve_voice(db, authorization)
    if provider is None:
        return _unauth_voice()
    calls = await list_calls_for(db, provider.id)
    return fmt.format_call_list(calls)


# ─────────────────────────────────────────────────────────────────────────────
# Numbers (account/numbers, number/search, number/buy, number/cancel)
# ─────────────────────────────────────────────────────────────────────────────


async def _resolve_account_creds(db: AsyncSession, request: Request) -> Any:
    params = request.query_params
    try:
        form = await request.form()
    except Exception:
        form = {}  # type: ignore[assignment]
    api_key = (
        params.get("api_key") or (form.get("api_key") if isinstance(form, dict) else None) or None
    )
    api_secret = (
        params.get("api_secret")
        or (form.get("api_secret") if isinstance(form, dict) else None)
        or None
    )
    if api_key is None or api_secret is None:
        return None
    return await _resolve_numbers(db, str(api_key), str(api_secret))


@router.get("/account/numbers")
async def owned_numbers(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    provider = await _resolve_account_creds(db, request)
    if provider is None:
        return JSONResponse(
            status_code=401,
            content={"error-code": "401", "error-code-label": "authentication failed"},
        )
    nums = await list_owned_numbers(db, provider.id)
    return fmt.format_owned_numbers(nums)


@router.get("/number/search/{country}")
async def search_numbers(
    country: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    pattern: str | None = Query(default=None),
    search_pattern: int = Query(default=0),
    number_type: str | None = Query(default=None, alias="type"),
) -> Any:
    provider = await _resolve_account_creds(db, request)
    if provider is None:
        return JSONResponse(
            status_code=401,
            content={"error-code": "401", "error-code-label": "authentication failed"},
        )
    mapped_type = {
        "mobile-lvn": "mobile",
        "landline": "local",
        "landline-toll-free": "tollfree",
    }.get(number_type or "landline", "local")
    numbers = get_available_numbers(
        iso_country=country,
        number_type=mapped_type,
        contains=pattern,
        page_size=50,
    )
    return fmt.format_available_numbers(numbers)


@router.post("/number/buy")
async def buy_number(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    provider = await _resolve_account_creds(db, request)
    if provider is None:
        return JSONResponse(
            status_code=401,
            content={"error-code": "401", "error-code-label": "authentication failed"},
        )
    params = dict(request.query_params)
    try:
        form = await request.form()
    except Exception:
        form = {}  # type: ignore[assignment]
    country = params.get("country") or (form.get("country") if isinstance(form, dict) else None)
    msisdn = params.get("msisdn") or (form.get("msisdn") if isinstance(form, dict) else None)
    if country is None or msisdn is None:
        return JSONResponse(
            status_code=400, content={"error-code": "400", "error-code-label": "bad request"}
        )
    e164 = "+" + str(msisdn).lstrip("+")
    mark_consumed(e164)
    pn = SandboxPhoneNumber(
        provider_id=provider.id,
        external_id="vn-" + e164.lstrip("+"),
        e164=e164,
        iso_country=str(country),
        number_type="local",
        capabilities={"voice": True, "sms": True, "mms": True, "fax": False},
    )
    db.add(pn)
    await db.commit()
    return {"error-code": "200", "error-code-label": "success"}


@router.post("/number/cancel")
async def cancel_number(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    from sqlalchemy import select

    provider = await _resolve_account_creds(db, request)
    if provider is None:
        return JSONResponse(
            status_code=401,
            content={"error-code": "401", "error-code-label": "authentication failed"},
        )
    params = dict(request.query_params)
    try:
        form = await request.form()
    except Exception:
        form = {}  # type: ignore[assignment]
    msisdn = params.get("msisdn") or (form.get("msisdn") if isinstance(form, dict) else None)
    if msisdn is None:
        return JSONResponse(
            status_code=400, content={"error-code": "400", "error-code-label": "bad request"}
        )
    e164 = "+" + str(msisdn).lstrip("+")
    stmt = select(SandboxPhoneNumber).where(
        SandboxPhoneNumber.provider_id == provider.id,
        SandboxPhoneNumber.e164 == e164,
    )
    result = await db.execute(stmt)
    pn = result.scalar_one_or_none()
    if pn is None:
        return JSONResponse(status_code=404, content={"error-code": "404"})
    pn.released = True
    release_consumed(e164)
    await db.commit()
    return {"error-code": "200", "error-code-label": "success"}


# ─────────────────────────────────────────────────────────────────────────────
# Not-supported: porting, TCR
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/number/port")
async def not_supported_port() -> Response:
    return Response(status_code=404, content="", media_type="text/plain")


@router.post("/csp/brands")
async def not_supported_brands() -> Response:
    return Response(status_code=404, content="", media_type="text/plain")


# ─────────────────────────────────────────────────────────────────────────────
# Provider class
# ─────────────────────────────────────────────────────────────────────────────


class VonageProvider(BaseSandboxProvider):
    provider_name = "vonage"

    def get_router(self) -> APIRouter:
        return router

    async def format_outbound_response(self, message: SandboxMessage) -> dict[str, Any]:
        return fmt.format_message_send_response(message)

    async def build_webhook_payload(
        self, message: SandboxMessage, event_type: str
    ) -> dict[str, Any]:
        channel = message.metadata_json.get("channel", "sms")
        if event_type == "message.status":
            return fmt.format_message_status_webhook(message, "delivered")
        return fmt.format_inbound_message_webhook(message, channel)

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return "api_key" in credentials and "api_secret" in credentials

    def get_sandbox_url_hint(self, provider: Any) -> str:
        return "/sandbox/vonage/v1/messages"
