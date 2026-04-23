"""Twilio REST API sandbox router and provider class.

Mounts three routers:

* ``/sandbox/twilio/2010-04-01/Accounts/{AccountSid}/...`` — Messages, Calls,
  IncomingPhoneNumbers, AvailablePhoneNumbers.
* ``/sandbox/twilio/v1/Porting/Orders`` — number porting.
* ``/sandbox/twilio/v1/a2p/...`` + ``/sandbox/twilio/v1/Services/...`` — brand
  and campaign registration, CustomerProfiles, TrustProducts.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.sandbox.models import SandboxMessage
from app.sandbox.providers.base import BaseSandboxProvider
from app.sandbox.providers.twilio import calls as twilio_calls
from app.sandbox.providers.twilio import numbers as twilio_numbers
from app.sandbox.providers.twilio import porting as twilio_porting
from app.sandbox.providers.twilio import trusthub as twilio_trusthub
from app.sandbox.providers.twilio.formatter import (
    format_message,
    format_message_list,
    generate_sid,
)
from app.sandbox.providers.twilio.schemas import SendSMSRequest
from app.sandbox.providers.twilio.service import extract_basic_auth, resolve_account
from app.sandbox.service import (
    get_messages,
    get_or_create_conversation,
    store_message,
    update_raw_response,
)

logger = logging.getLogger("mailcue.sandbox.twilio")

root_router = APIRouter(prefix="/sandbox/twilio", tags=["Sandbox - Twilio"])
messages_router = APIRouter(
    prefix="/sandbox/twilio/2010-04-01/Accounts", tags=["Sandbox - Twilio"]
)


def _unauth() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"code": 20003, "message": "Authenticate", "status": 401},
    )


async def _resolve_from_auth(
    db: AsyncSession,
    account_sid: str,
    authorization: str | None,
) -> Any:
    creds = extract_basic_auth(authorization)
    if creds is None:
        return None
    username, password = creds
    if username != account_sid:
        return None
    return await resolve_account(db, account_sid, password)


# ─────────────────────────────────────────────────────────────────────────────
# SMS / MMS
# ─────────────────────────────────────────────────────────────────────────────


async def _parse_send_body(request: Request) -> SendSMSRequest:
    """Accept either JSON (tests) or form-encoded bodies (real Twilio SDK)."""
    ct = (request.headers.get("content-type") or "").lower()
    if ct.startswith("application/x-www-form-urlencoded") or ct.startswith("multipart/form-data"):
        form = await request.form()
        media: list[str] = []
        for key in form:
            if key == "MediaUrl":
                values = form.getlist(key) if hasattr(form, "getlist") else [form.get(key)]
                media.extend([str(v) for v in values if v])
        payload = {k: str(v) for k, v in form.items() if k != "MediaUrl"}
        if media:
            payload["MediaUrl"] = media  # type: ignore[assignment]
        return SendSMSRequest(**payload)
    data: Any = await request.json()
    if isinstance(data, dict) and "MediaUrl" in data and isinstance(data["MediaUrl"], str):
        data = {**data, "MediaUrl": [data["MediaUrl"]]}
    return SendSMSRequest(**(data if isinstance(data, dict) else {}))


@messages_router.api_route("/{account_sid}/", methods=["GET", "POST"])
async def twilio_index(account_sid: str) -> Any:
    return {
        "description": "MailCue Twilio REST API Sandbox",
        "account_sid": account_sid,
    }


@messages_router.post("/{account_sid}/Messages.json")
async def send_sms(
    account_sid: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve_from_auth(db, account_sid, authorization)
    if provider is None:
        return _unauth()

    body = await _parse_send_body(request)
    sid = generate_sid("SM")
    from_number = body.From or (body.MessagingServiceSid or "")
    conv_ext = f"{from_number}->{body.To}"
    conv = await get_or_create_conversation(db, provider.id, conv_ext, conv_ext, "sms")
    media_urls: list[str] = []
    if isinstance(body.MediaUrl, list):
        media_urls = list(body.MediaUrl)
    elif isinstance(body.MediaUrl, str):
        media_urls = [body.MediaUrl]
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        from_number,
        body.Body,
        conversation_id=conv.id,
        content_type="mms" if media_urls else "sms",
        external_id=sid,
        raw_request=body.model_dump(exclude_none=True),
        metadata={
            "from": from_number,
            "to": body.To,
            "status_callback": body.StatusCallback,
            "media_urls": media_urls,
            "account_sid": account_sid,
        },
    )
    response = format_message(msg, account_sid)
    await update_raw_response(db, msg, response)
    return response


@messages_router.get("/{account_sid}/Messages.json")
async def list_messages(
    account_sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    page_size: int = Query(default=50, alias="PageSize"),
) -> Any:
    provider = await _resolve_from_auth(db, account_sid, authorization)
    if provider is None:
        return _unauth()

    messages, _ = await get_messages(db, provider.id, limit=page_size)
    active = [m for m in messages if not m.is_deleted]
    return format_message_list(active, account_sid)


@messages_router.get("/{account_sid}/Messages/{message_sid}.json")
async def get_message(
    account_sid: str,
    message_sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    provider = await _resolve_from_auth(db, account_sid, authorization)
    if provider is None:
        return _unauth()

    messages, _ = await get_messages(db, provider.id, limit=1000)
    for msg in messages:
        if msg.external_id == message_sid:
            return format_message(msg, account_sid)

    return JSONResponse(
        status_code=404,
        content={
            "code": 20404,
            "message": f"The requested resource /Messages/{message_sid}.json was not found",
            "status": 404,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Mount sub-routers (calls, numbers, porting, trusthub)
# ─────────────────────────────────────────────────────────────────────────────


messages_router.include_router(twilio_calls.router)
messages_router.include_router(twilio_numbers.router)
root_router.include_router(twilio_porting.router)
root_router.include_router(twilio_trusthub.router)


class TwilioProvider(BaseSandboxProvider):
    provider_name = "twilio"

    def __init__(self) -> None:
        self._aggregate = APIRouter()
        self._aggregate.include_router(messages_router)
        self._aggregate.include_router(root_router)

    def get_router(self) -> APIRouter:
        return self._aggregate

    async def format_outbound_response(self, message: SandboxMessage) -> dict[str, Any]:
        account_sid = message.metadata_json.get("account_sid", "")
        return format_message(message, account_sid)

    async def build_webhook_payload(
        self, message: SandboxMessage, event_type: str
    ) -> dict[str, Any]:
        return {
            "MessageSid": message.external_id or generate_sid("SM"),
            "AccountSid": message.metadata_json.get("account_sid", ""),
            "From": message.metadata_json.get("from", message.sender),
            "To": message.metadata_json.get("to", ""),
            "Body": message.content or "",
            "MessageStatus": event_type,
            "NumMedia": str(len(message.metadata_json.get("media_urls", []) or [])),
        }

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return "account_sid" in credentials and "auth_token" in credentials

    def get_sandbox_url_hint(self, provider: Any) -> str:
        account_sid = provider.credentials.get("account_sid", "{account_sid}")
        return f"/sandbox/twilio/2010-04-01/Accounts/{account_sid}/"


__all__ = ["AsyncSessionLocal", "TwilioProvider"]
