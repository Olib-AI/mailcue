"""Twilio REST API sandbox router and provider class."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.sandbox.models import SandboxMessage
from app.sandbox.providers.base import BaseSandboxProvider
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

router = APIRouter(prefix="/sandbox/twilio/2010-04-01/Accounts", tags=["Sandbox - Twilio"])

_UNAUTHORIZED = JSONResponse(
    status_code=401,
    content={"code": 20003, "message": "Authenticate", "status": 401},
)


async def _resolve_from_auth(
    db: AsyncSession,
    account_sid: str,
    authorization: str | None,
) -> Any:
    """Extract Basic auth credentials and resolve provider."""
    creds = extract_basic_auth(authorization)
    if creds is None:
        return None
    username, password = creds
    # The username in Basic auth must match the account_sid in the URL
    if username != account_sid:
        return None
    return await resolve_account(db, account_sid, password)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.api_route("/{account_sid}/", methods=["GET", "POST"])
async def twilio_index(account_sid: str) -> Any:
    """Index route showing available Twilio REST API sandbox endpoints."""
    return {
        "description": "MailCue Twilio REST API Sandbox",
        "account_sid": account_sid,
        "endpoints": [
            "POST /Messages.json",
            "GET  /Messages.json",
            "GET  /Messages/{sid}.json",
        ],
    }


@router.post("/{account_sid}/Messages.json")
async def send_sms(
    account_sid: str,
    body: SendSMSRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Emulate Twilio send SMS."""
    provider = await _resolve_from_auth(db, account_sid, authorization)
    if provider is None:
        return _UNAUTHORIZED

    sid = generate_sid("SM")
    conv_ext = f"{body.From}->{body.To}"
    conv = await get_or_create_conversation(db, provider.id, conv_ext, conv_ext, "sms")
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        body.From,
        body.Body,
        conversation_id=conv.id,
        content_type="text",
        external_id=sid,
        raw_request=body.model_dump(),
        metadata={"from": body.From, "to": body.To, "status_callback": body.StatusCallback},
    )
    response = format_message(msg, account_sid)
    await update_raw_response(db, msg, response)
    return response


@router.get("/{account_sid}/Messages.json")
async def list_messages(
    account_sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Emulate Twilio list messages."""
    provider = await _resolve_from_auth(db, account_sid, authorization)
    if provider is None:
        return _UNAUTHORIZED

    messages, _ = await get_messages(db, provider.id, limit=50)
    active = [m for m in messages if not m.is_deleted]
    return format_message_list(active, account_sid)


@router.get("/{account_sid}/Messages/{message_sid}.json")
async def get_message(
    account_sid: str,
    message_sid: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Emulate Twilio get message."""
    provider = await _resolve_from_auth(db, account_sid, authorization)
    if provider is None:
        return _UNAUTHORIZED

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


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------


class TwilioProvider(BaseSandboxProvider):
    """Twilio REST API sandbox provider."""

    provider_name = "twilio"

    def get_router(self) -> APIRouter:
        return router

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
        }

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return "account_sid" in credentials and "auth_token" in credentials

    def get_sandbox_url_hint(self, provider: Any) -> str:
        account_sid = provider.credentials.get("account_sid", "{account_sid}")
        return f"/sandbox/twilio/2010-04-01/Accounts/{account_sid}/"
