"""Telegram Bot API sandbox router and provider class."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.sandbox.models import SandboxMessage
from app.sandbox.providers.base import BaseSandboxProvider
from app.sandbox.providers.telegram.formatter import (
    format_bot_info,
    format_message,
    format_webhook_update,
)
from app.sandbox.providers.telegram.schemas import (
    DeleteMessageRequest,
    EditMessageRequest,
    GetUpdatesRequest,
    SendMessageRequest,
    SetWebhookRequest,
)
from app.sandbox.providers.telegram.service import (
    get_chat_id,
    next_message_id,
    next_update_id,
    resolve_bot_token,
)
from app.sandbox.service import (
    create_webhook_endpoint,
    delete_webhook_endpoint,
    get_messages,
    get_or_create_conversation,
    get_webhook_endpoints,
    store_message,
    update_raw_response,
)

logger = logging.getLogger("mailcue.sandbox.telegram")

router = APIRouter(prefix="/sandbox/telegram", tags=["Sandbox - Telegram"])

_UNAUTHORIZED: dict[str, Any] = {
    "ok": False,
    "error_code": 401,
    "description": "Unauthorized",
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.api_route("/bot{token}/", methods=["GET", "POST"])
async def telegram_index(token: str) -> dict[str, Any]:
    """Index route showing available Telegram Bot API sandbox endpoints."""
    return {
        "ok": True,
        "description": "MailCue Telegram Bot API Sandbox",
        "endpoints": [
            "POST /getMe",
            "POST /sendMessage",
            "POST /sendPhoto",
            "POST /sendDocument",
            "POST /editMessageText",
            "POST /deleteMessage",
            "POST /getUpdates",
            "POST /setWebhook",
            "POST /deleteWebhook",
            "POST /getWebhookInfo",
        ],
    }


@router.post("/bot{token}/getMe")
async def get_me(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Emulate Telegram getMe."""
    provider = await resolve_bot_token(db, token)
    if provider is None:
        return _UNAUTHORIZED
    return {"ok": True, "result": format_bot_info(provider)}


@router.post("/bot{token}/sendMessage")
async def send_message(
    token: str,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Emulate Telegram sendMessage."""
    provider = await resolve_bot_token(db, token)
    if provider is None:
        return _UNAUTHORIZED

    chat_id = get_chat_id(provider)
    conv = await get_or_create_conversation(
        db, provider.id, str(body.chat_id), f"Chat {body.chat_id}", "private"
    )
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        provider.name,
        body.text,
        conversation_id=conv.id,
        content_type="text",
        external_id=str(next_message_id(provider.id)),
        raw_request=body.model_dump(),
    )
    bot_info = format_bot_info(provider)
    formatted = format_message(msg, chat_id, bot_info=bot_info)
    response = {"ok": True, "result": formatted}
    await update_raw_response(db, msg, response)
    return response


@router.post("/bot{token}/sendPhoto")
async def send_photo(
    token: str,
    db: AsyncSession = Depends(get_db),
    chat_id: int | str | None = None,
    caption: str | None = None,
) -> dict[str, Any]:
    """Emulate Telegram sendPhoto."""
    provider = await resolve_bot_token(db, token)
    if provider is None:
        return _UNAUTHORIZED

    resolved_chat_id = get_chat_id(provider)
    target = str(chat_id) if chat_id is not None else str(resolved_chat_id)
    conv = await get_or_create_conversation(db, provider.id, target, f"Chat {target}", "private")
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        provider.name,
        caption or "[photo]",
        conversation_id=conv.id,
        content_type="photo",
        external_id=str(next_message_id(provider.id)),
        raw_request={"chat_id": str(chat_id), "caption": caption},
    )
    bot_info = format_bot_info(provider)
    formatted = format_message(msg, resolved_chat_id, bot_info=bot_info)
    response = {"ok": True, "result": formatted}
    await update_raw_response(db, msg, response)
    return response


@router.post("/bot{token}/sendDocument")
async def send_document(
    token: str,
    db: AsyncSession = Depends(get_db),
    chat_id: int | str | None = None,
    caption: str | None = None,
) -> dict[str, Any]:
    """Emulate Telegram sendDocument."""
    provider = await resolve_bot_token(db, token)
    if provider is None:
        return _UNAUTHORIZED

    resolved_chat_id = get_chat_id(provider)
    target = str(chat_id) if chat_id is not None else str(resolved_chat_id)
    conv = await get_or_create_conversation(db, provider.id, target, f"Chat {target}", "private")
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        provider.name,
        caption or "[document]",
        conversation_id=conv.id,
        content_type="document",
        external_id=str(next_message_id(provider.id)),
        raw_request={"chat_id": str(chat_id), "caption": caption},
    )
    bot_info = format_bot_info(provider)
    formatted = format_message(msg, resolved_chat_id, bot_info=bot_info)
    response = {"ok": True, "result": formatted}
    await update_raw_response(db, msg, response)
    return response


@router.post("/bot{token}/editMessageText")
async def edit_message_text(
    token: str,
    body: EditMessageRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Emulate Telegram editMessageText."""
    provider = await resolve_bot_token(db, token)
    if provider is None:
        return _UNAUTHORIZED

    import time

    chat_id = get_chat_id(provider)
    conv = await get_or_create_conversation(
        db, provider.id, str(body.chat_id), f"Chat {body.chat_id}", "private"
    )

    # Store edited message
    edit_ts = int(time.time())
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        provider.name,
        body.text,
        conversation_id=conv.id,
        content_type="text",
        external_id=str(body.message_id),
        raw_request=body.model_dump(),
        metadata={"edit_date": edit_ts, "edited": True},
    )
    bot_info = format_bot_info(provider)
    formatted = format_message(msg, chat_id, bot_info=bot_info)
    response = {"ok": True, "result": formatted}
    await update_raw_response(db, msg, response)
    return response


@router.post("/bot{token}/deleteMessage")
async def delete_message(
    token: str,
    body: DeleteMessageRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Emulate Telegram deleteMessage."""
    provider = await resolve_bot_token(db, token)
    if provider is None:
        return _UNAUTHORIZED

    # Mark matching messages as deleted
    messages, _ = await get_messages(db, provider.id)
    for msg in messages:
        if msg.external_id == str(body.message_id):
            msg.is_deleted = True
            await db.commit()
            break

    return {"ok": True, "result": True}


@router.post("/bot{token}/getUpdates")
async def get_updates(
    token: str,
    body: GetUpdatesRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Emulate Telegram getUpdates (long-polling stub)."""
    provider = await resolve_bot_token(db, token)
    if provider is None:
        return _UNAUTHORIZED

    if body is None:
        body = GetUpdatesRequest()

    chat_id = get_chat_id(provider)
    messages, _ = await get_messages(db, provider.id, limit=body.limit)

    # Filter to inbound only and apply offset
    updates: list[dict[str, object]] = []
    for msg in reversed(messages):
        if msg.direction != "inbound":
            continue
        update_id = next_update_id(provider.id)
        if body.offset is not None and update_id < body.offset:
            continue
        updates.append(format_webhook_update(msg, update_id, chat_id))

    return {"ok": True, "result": updates}


@router.post("/bot{token}/setWebhook")
async def set_webhook(
    token: str,
    body: SetWebhookRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Emulate Telegram setWebhook."""
    provider = await resolve_bot_token(db, token)
    if provider is None:
        return _UNAUTHORIZED

    # Remove existing webhooks first
    existing = await get_webhook_endpoints(db, provider.id)
    for ep in existing:
        await delete_webhook_endpoint(db, ep.id)

    await create_webhook_endpoint(
        db,
        provider.id,
        {
            "url": body.url,
            "secret": body.secret_token,
            "event_types": ["message"],
        },
    )
    return {"ok": True, "result": True, "description": "Webhook was set"}


@router.post("/bot{token}/deleteWebhook")
async def delete_webhook(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Emulate Telegram deleteWebhook."""
    provider = await resolve_bot_token(db, token)
    if provider is None:
        return _UNAUTHORIZED

    existing = await get_webhook_endpoints(db, provider.id)
    for ep in existing:
        await delete_webhook_endpoint(db, ep.id)

    return {"ok": True, "result": True, "description": "Webhook was deleted"}


@router.post("/bot{token}/getWebhookInfo")
async def get_webhook_info(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Emulate Telegram getWebhookInfo."""
    provider = await resolve_bot_token(db, token)
    if provider is None:
        return _UNAUTHORIZED

    endpoints = await get_webhook_endpoints(db, provider.id)
    if endpoints:
        ep = endpoints[0]
        return {
            "ok": True,
            "result": {
                "url": ep.url,
                "has_custom_certificate": False,
                "pending_update_count": 0,
            },
        }
    return {
        "ok": True,
        "result": {
            "url": "",
            "has_custom_certificate": False,
            "pending_update_count": 0,
        },
    }


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------


class TelegramProvider(BaseSandboxProvider):
    """Telegram Bot API sandbox provider."""

    provider_name = "telegram"

    def get_router(self) -> APIRouter:
        return router

    async def format_outbound_response(self, message: SandboxMessage) -> dict[str, Any]:
        chat_id = abs(hash(message.provider_id)) % (10**9)
        return format_message(message, chat_id)

    async def build_webhook_payload(
        self, message: SandboxMessage, event_type: str
    ) -> dict[str, Any]:
        chat_id = abs(hash(message.provider_id)) % (10**9)
        update_id = next_update_id(message.provider_id)
        return format_webhook_update(message, update_id, chat_id)

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return "bot_token" in credentials

    def get_sandbox_url_hint(self, provider: Any) -> str:
        token = provider.credentials.get("bot_token", "{bot_token}")
        return f"/sandbox/telegram/bot{token}/"
