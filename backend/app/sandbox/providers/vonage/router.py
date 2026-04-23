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
from app.sandbox.models import SandboxMessage, SandboxPhoneNumber, SandboxProvider
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
    _fire_webhooks,
    get_or_create_conversation,
    store_message,
    update_raw_response,
)
from app.sandbox.signers import (
    SigningFn,
    make_vonage_hs256_signer,
    make_vonage_messages_signer,
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


def _vonage_extract_msisdn(value: Any) -> str | None:
    """Extract an MSISDN from Vonage Messages v1 ``to`` / ``from`` fields.

    The real Messages API accepts a bare MSISDN string for the SMS
    channel and a ``{"type": "<channel>", "number": "..."}`` object for
    WhatsApp / MMS / Viber.  Returns ``None`` when the shape is
    unrecognised so the caller can emit a Vonage-shaped 422.
    """
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    if isinstance(value, dict):
        number = value.get("number")
        if isinstance(number, str) and number.strip():
            return number.strip()
        return None
    return None


def _vonage_invalid_request(detail: str) -> JSONResponse:
    """Return the 422 error body the real Vonage Messages v1 emits."""
    return JSONResponse(
        status_code=422,
        content={
            "type": "https://developer.vonage.com/api-errors/messages-olympus#1150",
            "title": "Invalid request body",
            "detail": detail,
            "instance": "mailcue-sandbox",
        },
    )


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
        return _vonage_invalid_request("body must be a JSON object")
    message_type = body.get("message_type", "text")
    channel = body.get("channel", "sms")

    # Vonage Messages v1 accepts ``to``/``from`` as bare MSISDN strings
    # for SMS and as ``{"type": "<channel>", "number": "..."}`` objects
    # for WhatsApp/MMS/Viber.  Accept both shapes and reject anything
    # else with the vendor's 422 shape.
    raw_to = body.get("to")
    raw_from = body.get("from")
    to_number = _vonage_extract_msisdn(raw_to)
    from_number = _vonage_extract_msisdn(raw_from)
    if raw_to is not None and to_number is None:
        return _vonage_invalid_request("'to' must be a string or object with 'number'")
    if raw_from is not None and from_number is None:
        return _vonage_invalid_request("'from' must be a string or object with 'number'")
    to_number = to_number or ""
    from_number = from_number or ""
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
    # Real Vonage Messages v1 sends a ``submitted`` status webhook right
    # after accepting a send request.  Fire the provider-formatted event
    # at every registered callback endpoint.
    _fire_webhooks(msg)
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
        form = None
    # FastAPI's ``request.form()`` returns ``FormData`` (not ``dict``),
    # but both expose ``.get(key)``; duck-type on ``callable(getattr(...))``.
    api_key = params.get("api_key") or (form.get("api_key") if form is not None else None)
    api_secret = params.get("api_secret") or (form.get("api_secret") if form is not None else None)
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


@router.get("/account/get-balance")
async def account_balance(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Vonage Account API ``GET /account/get-balance``.

    The real endpoint returns ``{"value": <EUR>, "autoReload": <bool>}``.
    fase's Vonage adapter uses it as the :meth:`verify_credentials`
    probe.  Auth uses ``api_key`` + ``api_secret`` on the query string.
    """
    provider = await _resolve_account_creds(db, request)
    if provider is None:
        return JSONResponse(
            status_code=401,
            content={"error-code": "401", "error-code-label": "authentication failed"},
        )
    return {"value": 10.0, "autoReload": False}


@router.get("/number/search")
async def search_numbers(
    request: Request,
    db: AsyncSession = Depends(get_db),
    country: str = Query(..., alias="country"),
    pattern: str | None = Query(default=None),
    search_pattern: int = Query(default=0),
    size: int = Query(default=10),
    features: str | None = Query(default=None),
    number_type: str | None = Query(default=None, alias="type"),
) -> Any:
    """Vonage Numbers API — search available numbers.

    Real endpoint: ``GET https://rest.nexmo.com/number/search`` with
    ``country`` / ``size`` / ``features`` / ``pattern`` / ``type`` as
    query parameters.  Authentication uses ``api_key`` + ``api_secret``
    carried either as query params (legacy) or as form fields.
    """
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

    # Translate Vonage ``features=SMS,VOICE,MMS`` into seed filters.
    feature_set = {f.strip().upper() for f in (features or "").split(",") if f.strip()}
    sms_flag: bool | None = True if "SMS" in feature_set else None
    voice_flag: bool | None = True if "VOICE" in feature_set else None
    mms_flag: bool | None = True if "MMS" in feature_set else None

    numbers = get_available_numbers(
        iso_country=country,
        number_type=mapped_type,
        contains=pattern,
        page_size=max(1, min(size, 100)),
        sms_enabled=sms_flag,
        voice_enabled=voice_flag,
        mms_enabled=mms_flag,
    )
    return fmt.format_available_numbers(numbers)


@router.get("/number/search/{country}")
async def search_numbers_legacy(country: str) -> JSONResponse:
    """Deprecated path-parameterised route — real Vonage never exposed
    this shape.  Kept as 410 Gone to surface misrouted callers loudly.
    """
    return JSONResponse(
        status_code=410,
        content={
            "error-code": "410",
            "error-code-label": (
                "path-parameterised /number/search/{country} is deprecated; "
                "use GET /number/search?country=... instead"
            ),
        },
    )


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
        form = None
    country = params.get("country") or (form.get("country") if form is not None else None)
    msisdn = params.get("msisdn") or (form.get("msisdn") if form is not None else None)
    if country is None or msisdn is None:
        return JSONResponse(
            status_code=400, content={"error-code": "400", "error-code-label": "bad request"}
        )
    e164 = "+" + str(msisdn).lstrip("+")
    mark_consumed(e164)
    # Idempotent: re-buying an already-owned number is a no-op in
    # Vonage's sandbox loop (real Vonage returns 401 with
    # "method-failed", which we simplify to the 200 success path so
    # repeat developer runs don't diverge).
    from sqlalchemy import select as _select

    existing = (
        (
            await db.execute(
                _select(SandboxPhoneNumber).where(
                    SandboxPhoneNumber.provider_id == provider.id,
                    SandboxPhoneNumber.e164 == e164,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing is None:
        db.add(
            SandboxPhoneNumber(
                provider_id=provider.id,
                external_id="vn-" + e164.lstrip("+"),
                e164=e164,
                iso_country=str(country),
                number_type="local",
                capabilities={"voice": True, "sms": True, "mms": True, "fax": False},
            ),
        )
        await db.commit()
    return {"error-code": "200", "error-code-label": "success"}


@router.post("/number/update")
async def update_number(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Set webhook URLs / application bindings on a purchased number.

    Real Vonage Numbers API accepts ``country``, ``msisdn``, and any
    combination of ``moHttpUrl`` / ``voiceCallbackType`` / ``app_id``
    as form fields and returns ``{"error-code": "200"}`` on success.
    """
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
        form = None
    msisdn = params.get("msisdn") or (form.get("msisdn") if form is not None else None)
    if msisdn is None:
        return JSONResponse(
            status_code=400,
            content={"error-code": "400", "error-code-label": "bad request"},
        )
    e164 = "+" + str(msisdn).lstrip("+")
    stmt = select(SandboxPhoneNumber).where(
        SandboxPhoneNumber.provider_id == provider.id,
        SandboxPhoneNumber.e164 == e164,
    )
    # Historical seeds / repeated test runs can leave multiple rows
    # for the same (provider, e164) pair — treat them all as aliases
    # of the same number and update the most recent.
    pn = (await db.execute(stmt)).scalars().first()
    if pn is None:
        return JSONResponse(
            status_code=404,
            content={"error-code": "404", "error-code-label": "not found"},
        )
    # Store any webhook-url-ish fields the caller sent.
    meta = dict(pn.metadata_json or {})
    for key in (
        "moHttpUrl",
        "voiceCallbackType",
        "voiceCallbackValue",
        "app_id",
        "voiceStatusCallback",
    ):
        val = params.get(key) or (form.get(key) if form is not None else None)
        if val is not None:
            meta[key] = str(val)
    if meta:
        pn.metadata_json = meta
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
        form = None
    msisdn = params.get("msisdn") or (form.get("msisdn") if form is not None else None)
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
        """Return Vonage Messages API v1 webhook shape.

        Inbound (``direction='inbound'``): ``{"message_uuid", "to": {"type":
        ..., "number": ...}, "from": {"type": ..., "number": ...},
        "timestamp", "channel", "message_type", "text", ...}`` — matches
        fase's ``vonage.parse_inbound_sms_webhook``.

        Outbound status: ``{"message_uuid", "to", "from", "timestamp",
        "status", "usage"}`` — matches ``vonage.parse_status_webhook``.
        """
        channel = message.metadata_json.get("channel", "sms") or "sms"
        if message.direction == "inbound":
            return fmt.format_inbound_message_webhook(message, channel)
        status = "submitted"
        if event_type in {"message.delivered", "delivered"}:
            status = "delivered"
        elif event_type in {"message.failed", "failed"}:
            status = "failed"
        return fmt.format_message_status_webhook(message, status)

    def build_webhook_signer(
        self,
        *,
        message: SandboxMessage,
        provider_record: SandboxProvider,
        url: str,
        payload_body: bytes,
    ) -> SigningFn | None:
        """Vonage Messages webhooks carry a Bearer JWT.

        The Messages API Application can be configured to sign webhooks
        either with the Application's asymmetric private key (RS256 /
        EdDSA) or with a shared ``signature_secret`` (HS256).  The
        consumer side must use the matching verifier — fase (and most
        modern Vonage SDK defaults) use HS256 with ``signature_secret``.
        We prefer ``signature_secret`` when present and fall back to
        ``private_key`` for environments that still run the legacy
        asymmetric flow.  If neither is saved we emit the request
        unsigned — matches Vonage's behaviour for Applications without a
        signing config.
        """
        del message, url, payload_body
        app_id = str(provider_record.credentials.get("application_id") or "")
        if not app_id:
            return None
        sig_secret = provider_record.credentials.get("signature_secret")
        if sig_secret:
            return make_vonage_hs256_signer(
                application_id=app_id,
                signature_secret=str(sig_secret),
            )
        priv_pem = provider_record.credentials.get("private_key")
        if priv_pem:
            return make_vonage_messages_signer(
                application_id=app_id,
                private_key_pem=str(priv_pem),
            )
        return None

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return "api_key" in credentials and "api_secret" in credentials

    def get_sandbox_url_hint(self, provider: Any) -> str:
        return "/sandbox/vonage/v1/messages"
