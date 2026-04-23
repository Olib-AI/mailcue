"""Bandwidth sandbox router: Messaging v2, Voice v2, Dashboard (XML), CSP."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.sandbox.models import SandboxMessage, SandboxProvider
from app.sandbox.providers.bandwidth import formatter as fmt
from app.sandbox.providers.bandwidth.schemas import (
    BandwidthBrandRequest,
    BandwidthCampaignRequest,
    BandwidthCreateCallRequest,
)
from app.sandbox.providers.bandwidth.service import (
    create_brand,
    create_call,
    create_campaign,
    create_number_order,
    create_phone_number,
    create_port_order,
    extract_basic_auth,
    get_brand,
    get_call,
    get_campaign,
    get_number_by_e164,
    get_order,
    get_port_order,
    list_calls_for,
    resolve_account,
    schedule_brand_approval,
    schedule_campaign_approval,
    schedule_port_lifecycle,
)
from app.sandbox.providers.base import BaseSandboxProvider
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
from app.sandbox.signers import SigningFn, make_bandwidth_signer
from app.sandbox.voice.worker import start_call

logger = logging.getLogger("mailcue.sandbox.bandwidth")


router = APIRouter(prefix="/sandbox/bandwidth", tags=["Sandbox - Bandwidth"])


def _unauth_json() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "type": "authentication-error",
            "description": "Invalid credentials",
        },
    )


def _unauth_xml() -> Response:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<ResponseSelectWrapper>"
        "<ListOrderIdUserIdDate/>"
        "<Error><Code>401</Code>"
        "<Description>Authentication failed.</Description></Error>"
        "</ResponseSelectWrapper>"
    )
    return Response(status_code=401, content=body, media_type="application/xml")


async def _resolve(db: AsyncSession, account_id: str, authorization: str | None) -> Any:
    creds = extract_basic_auth(authorization)
    if creds is None:
        return None
    username, password = creds
    return await resolve_account(db, account_id, username, password)


async def _resolve_dashboard(db: AsyncSession, account_id: str, authorization: str | None) -> Any:
    return await _resolve(db, account_id, authorization)


# ─────────────────────────────────────────────────────────────────────────────
# Messaging v2 (JSON)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/api/v2/users/{account_id}/messages")
async def send_message(
    account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_id, authorization)
    if provider is None:
        return _unauth_json()

    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(
            status_code=400,
            content={"type": "request-validation", "description": "Invalid body"},
        )
    to_list = body.get("to") or []
    if isinstance(to_list, str):
        to_list = [to_list]
    from_number = body.get("from", "")
    text = body.get("text", "")
    media = body.get("media") or []
    application_id = body.get("applicationId", "")

    msg_id = fmt.new_message_id()
    conv_ext = f"{from_number}->{','.join(to_list) if to_list else 'unknown'}"
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
            "to": to_list,
            "from": from_number,
            "application_id": application_id,
            "account_id": account_id,
            "media_urls": media,
            "tag": body.get("tag"),
        },
    )
    response = fmt.format_message(msg, account_id)
    await update_raw_response(db, msg, response)
    # Fire a ``message-sent``/``message-delivered``-style callback to every
    # registered application endpoint — mirrors how real Bandwidth posts
    # Messaging webhooks to the Application's callback URL.
    _fire_webhooks(msg)
    return JSONResponse(status_code=202, content=response)


@router.get("/api/v2/users/{account_id}/messages")
async def list_messages(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    from app.sandbox.service import get_messages

    provider = await _resolve(db, account_id, authorization)
    if provider is None:
        return _unauth_json()
    messages, _ = await get_messages(db, provider.id, limit=100)
    return {
        "totalCount": len(messages),
        "pageInfo": {
            "prevPage": None,
            "nextPage": None,
            "prevPageToken": None,
            "nextPageToken": None,
        },
        "messages": [fmt.format_message(m, account_id) for m in messages],
    }


@router.get("/api/v2/users/{account_id}/media")
async def list_media(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Bandwidth Messaging v2 ``GET /users/{accountId}/media``.

    Fase's :meth:`verify_credentials` probe hits this endpoint to assert
    the Basic-auth credentials are valid for the account.  The real API
    returns a JSON array of media metadata; we return an empty array
    (the sandbox never produces MMS media uploads) but **do** enforce
    auth so fase sees a 200 for good creds and 401 otherwise.
    """
    provider = await _resolve(db, account_id, authorization)
    if provider is None:
        return _unauth_json()
    return JSONResponse(status_code=200, content=[])


# ─────────────────────────────────────────────────────────────────────────────
# Voice v2 (JSON)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/api/v2/accounts/{account_id}/calls")
async def create_call_endpoint(
    account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_id, authorization)
    if provider is None:
        return _unauth_json()
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse(
            status_code=400,
            content={"type": "request-validation", "description": "Invalid body"},
        )
    # Bandwidth uses `from` not `from_`; re-map so Pydantic accepts it
    from_val = body.get("from")
    normalized = {**body, "from_": from_val}
    req = BandwidthCreateCallRequest(**normalized)

    call_id = fmt.new_call_id()
    call = await create_call(
        db,
        provider.id,
        call_id,
        from_number=req.from_ or "",
        to_number=req.to,
        application_id=req.applicationId,
        answer_url=req.answerUrl,
        answer_method=req.answerMethod,
        disconnect_url=req.disconnectUrl,
        raw_request=body,
    )

    async def _status_cb(status: str, call_snap: Any, extra: dict[str, Any]) -> None:
        # Bandwidth emits JSON "Voice Application" webhooks (callInitiated/
        # callAnswered/callDisconnected) on state transitions.  Authentication
        # uses HTTP Basic with the callback_username/callback_password saved
        # on the SandboxProvider (same value-shape as the real Bandwidth
        # Voice/Messaging Application settings).
        from app.sandbox.signers import make_bandwidth_signer
        from app.sandbox.webhook_raw import post_json

        if call_snap.metadata_json.get("disconnect_url") is None and call_snap.answer_url is None:
            return
        map_event = {
            "initiated": "initiate",
            "ringing": "initiate",
            "answered": "answer",
            "completed": "disconnect",
            "failed": "disconnect",
            "canceled": "disconnect",
        }
        event_type = map_event.get(status)
        if event_type is None:
            return
        payload = [
            {
                "eventType": event_type,
                "eventTime": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "accountId": account_id,
                "applicationId": call_snap.metadata_json.get("application_id", ""),
                "from": call_snap.from_number,
                "to": call_snap.to_number,
                "direction": "outbound",
                "callId": call_snap.external_id,
                "callUrl": f"https://voice.bandwidth.com/api/v2/accounts/{account_id}/calls/{call_snap.external_id}",
            }
        ]
        target = (
            call_snap.metadata_json.get("disconnect_url")
            if event_type == "disconnect"
            else call_snap.answer_url
        )
        if target:
            signer = make_bandwidth_signer(
                callback_username=provider.credentials.get("callback_username"),
                callback_password=provider.credentials.get("callback_password"),
            )
            await post_json(target, payload, signer=signer)

    start_call(
        call_id=call.id,
        provider_type="bandwidth",
        seed_digits=provider.credentials.get("sandbox_seed_digits", "1"),
        seed_speech=provider.credentials.get("sandbox_seed_speech", "yes"),
        status_cb=_status_cb,
    )

    return JSONResponse(status_code=201, content=fmt.format_call(call, account_id))


@router.get("/api/v2/accounts/{account_id}/calls")
async def list_calls(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_id, authorization)
    if provider is None:
        return _unauth_json()
    calls = await list_calls_for(db, provider.id)
    return [fmt.format_call(c, account_id) for c in calls]


@router.get("/api/v2/accounts/{account_id}/calls/{call_id}")
async def fetch_call(
    account_id: str,
    call_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_id, authorization)
    if provider is None:
        return _unauth_json()
    call = await get_call(db, provider.id, call_id)
    if call is None:
        return JSONResponse(
            status_code=404,
            content={"type": "not-found", "description": "Call not found"},
        )
    return fmt.format_call(call, account_id)


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard / Numbers API (XML)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/api/accounts/{account_id}")
async def fetch_dashboard_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Bandwidth Dashboard ``GET /api/accounts/{accountId}`` (XML).

    The real Dashboard API exposes basic account metadata here.  We
    return a minimal ``<AccountResponse><Account>...</Account></AccountResponse>``
    tree containing the account id + friendly name so consumers can
    sanity-check their credentials.
    """
    provider = await _resolve_dashboard(db, account_id, authorization)
    if provider is None:
        return _unauth_xml()
    company = (
        (provider.name or f"Mailcue Sandbox Account {account_id}")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<AccountResponse>"
        "<Account>"
        f"<AccountId>{account_id}</AccountId>"
        f"<CompanyName>{company}</CompanyName>"
        "<AccountType>Business</AccountType>"
        "</Account>"
        "</AccountResponse>"
    )
    return Response(content=body, media_type="application/xml")


@router.get("/api/accounts/{account_id}/availableNumbers")
async def available_numbers_search(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    area_code: str | None = Query(default=None, alias="areaCode"),
    quantity: int = Query(default=50, alias="quantity"),
    pattern: str | None = Query(default=None, alias="pattern"),
    toll_free_wildcard_pattern: str | None = Query(default=None, alias="tollFreeWildCardPattern"),
    lata: str | None = Query(default=None, alias="lata"),
    state: str | None = Query(default=None, alias="state"),
) -> Any:
    """Bandwidth Dashboard/Numbers API — GET availableNumbers.

    Real endpoint lives at
    ``https://dashboard.bandwidth.com/api/accounts/{accountId}/availableNumbers``
    and returns an XML ``<SearchResult>`` body.  The ``pattern`` query
    param accepts Bandwidth's wildcard syntax; ``tollFreeWildCardPattern``
    signals toll-free search.  ``quantity`` caps at 5000 per the real
    API but our seed pool returns at most ``page_size`` entries.
    """
    provider = await _resolve_dashboard(db, account_id, authorization)
    if provider is None:
        return _unauth_xml()

    # ``tollFreeWildCardPattern`` is mutually exclusive with ``pattern``
    # on real Bandwidth — either signals toll-free search or triggers an
    # ApiError.  We emulate the canonical case: if the toll-free
    # parameter is present, return toll-free entries from the seed pool.
    number_type = "tollfree" if toll_free_wildcard_pattern is not None else "local"

    # Bandwidth's ``pattern`` syntax allows a leading/trailing ``*``
    # wildcard.  We treat any non-wildcard middle substring as a
    # ``contains`` filter so seed lookup matches the real API's intent.
    contains: str | None = None
    if pattern:
        contains = pattern.strip("*") or None

    numbers = get_available_numbers(
        iso_country="US",
        number_type=number_type,
        area_code=area_code,
        contains=contains,
        page_size=quantity,
    )
    return Response(
        content=fmt.format_available_numbers_xml(numbers),
        media_type="application/xml",
    )


@router.post("/accounts/{account_id}/availableTelephoneNumbers", response_model=None)
@router.get("/accounts/{account_id}/availableTelephoneNumbers", response_model=None)
async def available_numbers_search_gone(account_id: str) -> Response:
    """Legacy mailcue path kept as 410 Gone for 30 days.

    The canonical endpoint lives at
    ``GET /api/accounts/{accountId}/availableNumbers`` matching the real
    Bandwidth Dashboard/Numbers API.  Any caller still pointing at the
    old path gets a loud, unambiguous 410 rather than silent breakage.
    """
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Error><Code>410</Code>"
        "<Description>availableTelephoneNumbers is deprecated; use "
        f"GET /api/accounts/{account_id}/availableNumbers instead."
        "</Description></Error>"
    )
    return Response(status_code=410, content=body, media_type="application/xml")


@router.post("/api/accounts/{account_id}/orders")
async def order_numbers(
    account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve_dashboard(db, account_id, authorization)
    if provider is None:
        return _unauth_xml()
    raw_body = (await request.body()).decode("utf-8")
    parsed = fmt.parse_order_xml(raw_body)
    sid = fmt.new_order_id()
    numbers = parsed.get("numbers", [])
    order = await create_number_order(
        db, provider.id, sid, numbers=numbers, raw_request={"raw_xml": raw_body}
    )
    # Register phone numbers
    for e164 in numbers:
        mark_consumed(e164)
        # Look up metadata in the seed pool
        caps = {"voice": True, "sms": True, "mms": True, "fax": False}
        await create_phone_number(
            db, provider.id, "N" + uuid.uuid4().hex[:15], e164=e164, capabilities=caps
        )
    return Response(
        content=fmt.format_order_xml(order, numbers),
        media_type="application/xml",
    )


@router.get("/api/accounts/{account_id}/orders/{order_id}")
async def fetch_order(
    account_id: str,
    order_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve_dashboard(db, account_id, authorization)
    if provider is None:
        return _unauth_xml()
    order = await get_order(db, provider.id, order_id)
    if order is None:
        return Response(
            status_code=404,
            content=(
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<OrderResponse><Error><Description>Order not found</Description></Error></OrderResponse>"
            ),
            media_type="application/xml",
        )
    return Response(
        content=fmt.format_order_xml(order, order.numbers),
        media_type="application/xml",
    )


@router.put("/api/accounts/{account_id}/phonenumbers/{tn}/messagingsettings")
async def set_messaging_settings(
    account_id: str,
    tn: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve_dashboard(db, account_id, authorization)
    if provider is None:
        return _unauth_xml()
    e164 = "+1" + tn if not tn.startswith("+") else tn
    pn = await get_number_by_e164(db, provider.id, e164)
    if pn is None:
        return Response(
            status_code=404,
            content='<?xml version="1.0"?><Error>Not found</Error>',
            media_type="application/xml",
        )
    raw = (await request.body()).decode("utf-8")
    # Minimal parser: grab <ApplicationId>
    import re as _re

    m = _re.search(r"<ApplicationId>([^<]+)</ApplicationId>", raw)
    app_id = m.group(1) if m else ""
    pn.metadata_json = {**pn.metadata_json, "messaging_application_id": app_id}
    await db.commit()
    await db.refresh(pn)
    return Response(content=fmt.format_messaging_settings_xml(pn), media_type="application/xml")


@router.put("/api/accounts/{account_id}/phonenumbers/{tn}/voicesettings")
async def set_voice_settings(
    account_id: str,
    tn: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve_dashboard(db, account_id, authorization)
    if provider is None:
        return _unauth_xml()
    e164 = "+1" + tn if not tn.startswith("+") else tn
    pn = await get_number_by_e164(db, provider.id, e164)
    if pn is None:
        return Response(
            status_code=404,
            content='<?xml version="1.0"?><Error>Not found</Error>',
            media_type="application/xml",
        )
    raw = (await request.body()).decode("utf-8")
    import re as _re

    m = _re.search(r"<ApplicationId>([^<]+)</ApplicationId>", raw)
    app_id = m.group(1) if m else ""
    pn.metadata_json = {**pn.metadata_json, "voice_application_id": app_id}
    await db.commit()
    await db.refresh(pn)
    return Response(content=fmt.format_voice_settings_xml(pn), media_type="application/xml")


@router.delete(
    "/api/accounts/{account_id}/phonenumbers/{tn}", status_code=204, response_model=None
)
async def release_number(
    account_id: str,
    tn: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve_dashboard(db, account_id, authorization)
    if provider is None:
        return _unauth_xml()
    e164 = "+1" + tn if not tn.startswith("+") else tn
    pn = await get_number_by_e164(db, provider.id, e164)
    if pn is None:
        return Response(
            status_code=404,
            content='<?xml version="1.0"?><Error>Not found</Error>',
            media_type="application/xml",
        )
    pn.released = True
    release_consumed(pn.e164)
    await db.commit()
    return Response(status_code=204)


@router.post("/api/accounts/{account_id}/portIns")
async def create_port_in(
    account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve_dashboard(db, account_id, authorization)
    if provider is None:
        return _unauth_xml()
    raw = (await request.body()).decode("utf-8")
    parsed = fmt.parse_port_in_xml(raw)
    sid = fmt.new_port_id()
    order = await create_port_order(
        db,
        provider.id,
        sid,
        numbers=parsed.get("numbers", []),
        loa_info=parsed.get("loa_info", {}),
        raw_request={"raw_xml": raw},
        customer_order_id=parsed.get("customer_order_id", ""),
    )
    schedule_port_lifecycle(
        AsyncSessionLocal,
        provider.id,
        sid,
        ["SUBMITTED", "APPROVED", "FOC", "COMPLETED"],
    )
    return Response(content=fmt.format_port_in_xml(order), media_type="application/xml")


@router.get("/api/accounts/{account_id}/portIns/{port_id}")
async def fetch_port_in(
    account_id: str,
    port_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve_dashboard(db, account_id, authorization)
    if provider is None:
        return _unauth_xml()
    order = await get_port_order(db, provider.id, port_id)
    if order is None:
        return Response(
            status_code=404,
            content='<?xml version="1.0"?><Error>Not found</Error>',
            media_type="application/xml",
        )
    return Response(content=fmt.format_port_in_xml(order), media_type="application/xml")


# ─────────────────────────────────────────────────────────────────────────────
# CSP (10DLC) — JSON
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/api/accounts/{account_id}/csp/brands")
async def create_brand_endpoint(
    account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_id, authorization)
    if provider is None:
        return _unauth_json()
    data = await request.json()
    if not isinstance(data, dict):
        return JSONResponse(status_code=400, content={"description": "Invalid body"})
    body = BandwidthBrandRequest(**data)
    sid = fmt.new_brand_id()
    brand = await create_brand(db, provider.id, sid, body.model_dump())
    schedule_brand_approval(AsyncSessionLocal, provider.id, sid)
    return JSONResponse(status_code=201, content=fmt.format_brand(brand))


@router.get("/api/accounts/{account_id}/csp/brands/{brand_id}")
async def fetch_brand(
    account_id: str,
    brand_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_id, authorization)
    if provider is None:
        return _unauth_json()
    brand = await get_brand(db, provider.id, brand_id)
    if brand is None:
        return JSONResponse(
            status_code=404, content={"type": "not-found", "description": "Brand not found"}
        )
    return fmt.format_brand(brand)


@router.post("/api/accounts/{account_id}/csp/campaigns")
async def create_campaign_endpoint(
    account_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_id, authorization)
    if provider is None:
        return _unauth_json()
    data = await request.json()
    if not isinstance(data, dict):
        return JSONResponse(status_code=400, content={"description": "Invalid body"})
    body = BandwidthCampaignRequest(**data)
    brand = await get_brand(db, provider.id, body.brandId)
    sid = fmt.new_campaign_id()
    campaign = await create_campaign(
        db,
        provider.id,
        sid,
        brand.id if brand is not None else None,
        body.model_dump(),
    )
    schedule_campaign_approval(AsyncSessionLocal, provider.id, sid)
    return JSONResponse(status_code=201, content=fmt.format_campaign(campaign))


@router.get("/api/accounts/{account_id}/csp/campaigns/{campaign_id}")
async def fetch_campaign(
    account_id: str,
    campaign_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve(db, account_id, authorization)
    if provider is None:
        return _unauth_json()
    campaign = await get_campaign(db, provider.id, campaign_id)
    if campaign is None:
        return JSONResponse(
            status_code=404,
            content={"type": "not-found", "description": "Campaign not found"},
        )
    return fmt.format_campaign(campaign)


# ─────────────────────────────────────────────────────────────────────────────
# Provider class
# ─────────────────────────────────────────────────────────────────────────────


class BandwidthProvider(BaseSandboxProvider):
    provider_name = "bandwidth"

    def get_router(self) -> APIRouter:
        return router

    async def format_outbound_response(self, message: SandboxMessage) -> dict[str, Any]:
        account_id = message.metadata_json.get("account_id", "")
        return fmt.format_message(message, account_id)

    async def build_webhook_payload(
        self, message: SandboxMessage, event_type: str
    ) -> list[dict[str, Any]]:
        """Bandwidth always delivers webhooks as a JSON array of events.

        Inbound format: ``[{"type": "message-received", "time": ..., "description": ...,
        "to": "<dest>", "message": {"id": ..., "owner": "<dest>", "applicationId": ...,
        "time": ..., "segmentCount": 1, "direction": "in", "to": ["<dest>"],
        "from": "<src>", "text": "..."}}]`` — matches fase's
        ``parse_inbound_sms_webhook`` expectation that the first array
        element carries a ``message`` object with ``id`` / ``from`` / ``to`` /
        ``text``.

        Status callback format uses ``type="message-sent"`` /
        ``"message-delivered"`` / ``"message-failed"`` depending on
        ``event_type``.
        """
        account_id = message.metadata_json.get("account_id", "")
        to_raw = message.metadata_json.get("to")
        to_list: list[str]
        if isinstance(to_raw, list):
            to_list = [str(t) for t in to_raw]
        elif to_raw:
            to_list = [str(to_raw)]
        else:
            to_list = [""]
        from_number = message.metadata_json.get("from", message.sender)
        media = message.metadata_json.get("media_urls") or []
        now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")

        if message.direction == "inbound":
            # Canonical Bandwidth v2 inbound message envelope.
            return [
                {
                    "type": "message-received",
                    "time": now_iso,
                    "description": "Incoming message received",
                    "to": to_list[0],
                    "message": {
                        "id": message.external_id or fmt.new_message_id(),
                        "owner": to_list[0],
                        "applicationId": message.metadata_json.get("application_id", ""),
                        "time": now_iso,
                        "segmentCount": 1,
                        "direction": "in",
                        "to": to_list,
                        "from": from_number,
                        "text": message.content or "",
                        "media": list(media),
                    },
                }
            ]

        status_map = {
            "message.created": "message-sent",
            "message.sent": "message-sent",
            "message.delivered": "message-delivered",
            "message.failed": "message-failed",
        }
        envelope_type = status_map.get(event_type, "message-sent")
        return [
            {
                "type": envelope_type,
                "time": now_iso,
                "description": envelope_type.replace("-", " ").capitalize(),
                "to": to_list[0],
                "message": fmt.format_message(message, account_id),
            }
        ]

    def build_webhook_signer(
        self,
        *,
        message: SandboxMessage,
        provider_record: SandboxProvider,
        url: str,
        payload_body: bytes,
    ) -> SigningFn | None:
        """Attach HTTP Basic to the webhook POST.

        Real Bandwidth Voice/Messaging Applications let operators configure
        *separate* callback credentials (``callback_username`` /
        ``callback_password``) from the API credentials (``user_id`` /
        ``password``).  fase's verification reuses the API credentials,
        so we prefer the callback pair only when it's explicitly set and
        otherwise fall back to the API credentials that every Bandwidth
        consumer knows by default.
        """
        del message, url, payload_body
        creds = provider_record.credentials
        user = creds.get("callback_username") or creds.get("user_id") or creds.get("username")
        password = creds.get("callback_password") or creds.get("password")
        return make_bandwidth_signer(
            callback_username=user,
            callback_password=password,
        )

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return all(k in credentials for k in ("username", "password", "account_id"))

    def get_sandbox_url_hint(self, provider: Any) -> str:
        account_id = provider.credentials.get("account_id", "{account_id}")
        return f"/sandbox/bandwidth/api/v2/users/{account_id}/messages"
