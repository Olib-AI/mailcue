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
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.sandbox.models import SandboxMessage, SandboxProvider
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
    _fire_webhooks,
    get_messages,
    get_or_create_conversation,
    store_message,
    update_raw_response,
)
from app.sandbox.signers import SigningFn, make_twilio_signer

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


@messages_router.get("/{account_sid}.json")
async def fetch_account(
    account_sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Twilio ``GET /2010-04-01/Accounts/{AccountSid}.json``.

    The Twilio Python SDK issues this call from
    ``client.api.accounts(sid).fetch()``; fase's Phone-Number adapter
    uses it as the :meth:`verify_credentials` probe.  Returns the real
    Account resource shape.
    """
    provider = await _resolve_from_auth(db, account_sid, authorization)
    if provider is None:
        return _unauth()
    created_at = provider.created_at
    date_created = created_at.strftime("%a, %d %b %Y %H:%M:%S +0000") if created_at else None
    friendly_name = provider.name or f"Mailcue Sandbox ({account_sid})"
    base_uri = f"/2010-04-01/Accounts/{account_sid}"
    return {
        "sid": account_sid,
        "friendly_name": friendly_name,
        "status": "active",
        "type": "Full",
        "auth_token": "[REDACTED]",
        "owner_account_sid": account_sid,
        "date_created": date_created,
        "date_updated": date_created,
        "uri": f"{base_uri}.json",
        "subresource_uris": {
            "addresses": f"{base_uri}/Addresses.json",
            "applications": f"{base_uri}/Applications.json",
            "authorized_connect_apps": f"{base_uri}/AuthorizedConnectApps.json",
            "available_phone_numbers": f"{base_uri}/AvailablePhoneNumbers.json",
            "balance": f"{base_uri}/Balance.json",
            "calls": f"{base_uri}/Calls.json",
            "conferences": f"{base_uri}/Conferences.json",
            "connect_apps": f"{base_uri}/ConnectApps.json",
            "incoming_phone_numbers": f"{base_uri}/IncomingPhoneNumbers.json",
            "keys": f"{base_uri}/Keys.json",
            "messages": f"{base_uri}/Messages.json",
            "notifications": f"{base_uri}/Notifications.json",
            "outgoing_caller_ids": f"{base_uri}/OutgoingCallerIds.json",
            "queues": f"{base_uri}/Queues.json",
            "recordings": f"{base_uri}/Recordings.json",
            "signing_keys": f"{base_uri}/SigningKeys.json",
            "sip": f"{base_uri}/SIP.json",
            "short_codes": f"{base_uri}/SMS/ShortCodes.json",
            "tokens": f"{base_uri}/Tokens.json",
            "transcriptions": f"{base_uri}/Transcriptions.json",
            "usage": f"{base_uri}/Usage.json",
            "validation_requests": f"{base_uri}/OutgoingCallerIds.json",
        },
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
    # Real Twilio emits a ``MessageStatus=queued`` callback right after
    # accepting the send request.  The webhook worker resolves every
    # registered application-level callback URL for the account and posts
    # the form-encoded event there.
    _fire_webhooks(msg)
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
        """Build a real-Twilio-shaped webhook payload.

        Inbound SMS (``message.direction == 'inbound'``) matches the form
        fields Twilio POSTs to the Messaging URL on an incoming message:
        ``MessageSid``, ``AccountSid``, ``From``, ``To``, ``Body``,
        ``NumMedia``, ``NumSegments``, plus ``MediaUrl0..N`` / the matching
        ``MediaContentType0..N`` when MMS is present — the exact shape
        fase's ``parse_inbound_sms_webhook`` adapter consumes.

        Outbound status callbacks match Twilio's ``MessageStatus`` callback
        (``queued`` → ``sent`` → ``delivered``) with ``MessageSid``,
        ``AccountSid``, ``From``, ``To``, ``Body``, ``MessageStatus``.
        """
        media_urls: list[str] = message.metadata_json.get("media_urls", []) or []
        account_sid = message.metadata_json.get("account_sid", "")
        from_number = message.metadata_json.get("from", message.sender)
        to_number = message.metadata_json.get("to", "")
        # Every SID field must reference the SAME SID so fase's
        # ``twilio.request_validator.RequestValidator`` recomputes the same
        # signing base.  Use ``external_id`` when present; fall back to a
        # stable derivation from ``message.id`` so repeat webhook builds
        # (e.g. retry attempts) produce identical payloads.
        sid = message.external_id or f"SM{message.id.replace('-', '')}"
        if message.direction == "inbound":
            payload: dict[str, Any] = {
                "MessageSid": sid,
                "SmsMessageSid": sid,
                "SmsSid": sid,
                "AccountSid": account_sid,
                "From": from_number,
                "To": to_number,
                "Body": message.content or "",
                "NumMedia": str(len(media_urls)),
                "NumSegments": "1",
                "ApiVersion": "2010-04-01",
            }
            for idx, url in enumerate(media_urls):
                payload[f"MediaUrl{idx}"] = url
                payload[f"MediaContentType{idx}"] = "image/jpeg"
            return payload
        # Outbound status callback.
        status = event_type.removeprefix("message.") if "." in event_type else event_type
        if status in {"created", "received"}:
            status = "queued"
        return {
            "MessageSid": sid,
            "SmsMessageSid": sid,
            "SmsSid": sid,
            "AccountSid": account_sid,
            "From": from_number,
            "To": to_number,
            "Body": message.content or "",
            "MessageStatus": status,
            "NumMedia": str(len(media_urls)),
            "NumSegments": "1",
            "ApiVersion": "2010-04-01",
        }

    def webhook_content_type(
        self, message: SandboxMessage, event_type: str
    ) -> Literal["json", "form"]:
        # Twilio *always* posts SMS + status callbacks form-encoded; the
        # JSON variant with ``X-Twilio-Content-Sha256`` is reserved for
        # the newer TaskRouter APIs and is not how SMS webhooks travel.
        del message, event_type
        return "form"

    def build_webhook_signer(
        self,
        *,
        message: SandboxMessage,
        provider_record: SandboxProvider,
        url: str,
        payload_body: bytes,
    ) -> SigningFn | None:
        """Sign with ``X-Twilio-Signature`` (HMAC-SHA1 over URL + sorted form)."""
        del payload_body
        auth_token = str(provider_record.credentials.get("auth_token") or "")
        if not auth_token:
            return None
        # Rebuild the form dict we'll be signing — must match
        # ``build_webhook_payload`` byte-for-byte so the receiver sees the
        # same (url, form_params) basis for its own HMAC.
        media_urls: list[str] = message.metadata_json.get("media_urls", []) or []
        account_sid = message.metadata_json.get("account_sid", "")
        from_number = message.metadata_json.get("from", message.sender)
        to_number = message.metadata_json.get("to", "")
        sid = message.external_id or f"SM{message.id.replace('-', '')}"
        form_params: dict[str, Any] = {
            "MessageSid": sid,
            "SmsMessageSid": sid,
            "SmsSid": sid,
            "AccountSid": account_sid,
            "From": from_number,
            "To": to_number,
            "Body": message.content or "",
            "NumMedia": str(len(media_urls)),
            "NumSegments": "1",
            "ApiVersion": "2010-04-01",
        }
        if message.direction != "inbound":
            form_params["MessageStatus"] = "queued"
        for idx, murl in enumerate(media_urls):
            form_params[f"MediaUrl{idx}"] = murl
            form_params[f"MediaContentType{idx}"] = "image/jpeg"
        return make_twilio_signer(
            auth_token=auth_token,
            url=url,
            form_params=form_params,
        )

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return "account_sid" in credentials and "auth_token" in credentials

    def get_sandbox_url_hint(self, provider: Any) -> str:
        account_sid = provider.credentials.get("account_sid", "{account_sid}")
        return f"/sandbox/twilio/2010-04-01/Accounts/{account_sid}/"


__all__ = ["AsyncSessionLocal", "TwilioProvider"]
