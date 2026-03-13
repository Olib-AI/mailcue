"""Slack Web API sandbox router and provider class."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.sandbox.models import SandboxMessage
from app.sandbox.providers.base import BaseSandboxProvider
from app.sandbox.providers.slack.formatter import (
    format_channel,
    format_event_payload,
    format_message,
    format_user,
)
from app.sandbox.providers.slack.schemas import (
    ChatDeleteRequest,
    ChatPostMessageRequest,
    ChatUpdateRequest,
)
from app.sandbox.providers.slack.service import generate_ts, resolve_bot_token
from app.sandbox.service import (
    get_messages,
    get_or_create_conversation,
    store_message,
    update_raw_response,
)

logger = logging.getLogger("mailcue.sandbox.slack")

router = APIRouter(prefix="/sandbox/slack/api", tags=["Sandbox - Slack"])

_INVALID_AUTH: dict[str, Any] = {"ok": False, "error": "invalid_auth"}


async def _resolve_from_header(
    db: AsyncSession,
    authorization: str | None,
) -> Any:
    """Extract bearer token from Authorization header and resolve provider."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return await resolve_bot_token(db, token)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.api_route("/", methods=["GET", "POST"])
async def slack_index() -> dict[str, Any]:
    """Index route showing available Slack Web API sandbox endpoints."""
    return {
        "ok": True,
        "description": "MailCue Slack Web API Sandbox",
        "endpoints": [
            "POST /chat.postMessage",
            "POST /chat.update",
            "POST /chat.delete",
            "GET  /conversations.list",
            "GET  /conversations.info",
            "GET  /conversations.history",
            "GET  /users.list",
            "GET  /users.info",
        ],
    }


@router.post("/chat.postMessage")
async def chat_post_message(
    body: ChatPostMessageRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Emulate Slack chat.postMessage."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _INVALID_AUTH

    conv = await get_or_create_conversation(db, provider.id, body.channel, body.channel, "channel")
    ts = generate_ts()
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        provider.name,
        body.text,
        conversation_id=conv.id,
        content_type="text",
        external_id=ts,
        raw_request=body.model_dump(),
        metadata={"thread_ts": body.thread_ts} if body.thread_ts else None,
    )
    formatted = format_message(msg, body.channel)
    response = {"ok": True, "channel": body.channel, "ts": ts, "message": formatted}
    await update_raw_response(db, msg, response)
    return response


@router.post("/chat.update")
async def chat_update(
    body: ChatUpdateRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Emulate Slack chat.update."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _INVALID_AUTH

    conv = await get_or_create_conversation(db, provider.id, body.channel, body.channel, "channel")
    ts = generate_ts()
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        provider.name,
        body.text,
        conversation_id=conv.id,
        content_type="text",
        external_id=ts,
        raw_request=body.model_dump(),
        metadata={"edited": True, "original_ts": body.ts},
    )
    formatted = format_message(msg, body.channel)
    response = {"ok": True, "channel": body.channel, "ts": ts, "message": formatted}
    await update_raw_response(db, msg, response)
    return response


@router.post("/chat.delete")
async def chat_delete(
    body: ChatDeleteRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Emulate Slack chat.delete."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _INVALID_AUTH

    # Mark messages with matching ts as deleted
    messages, _ = await get_messages(db, provider.id)
    for msg in messages:
        if msg.external_id == body.ts:
            msg.is_deleted = True
            await db.commit()
            break

    return {"ok": True, "channel": body.channel, "ts": body.ts}


@router.get("/conversations.list")
async def conversations_list(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Emulate Slack conversations.list."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _INVALID_AUTH

    from sqlalchemy import select

    from app.sandbox.models import SandboxConversation

    stmt = select(SandboxConversation).where(SandboxConversation.provider_id == provider.id)
    result = await db.execute(stmt)
    convs = result.scalars().all()
    channels = [format_channel(c) for c in convs]
    return {"ok": True, "channels": channels}


@router.get("/conversations.info")
async def conversations_info(
    channel: str = Query(...),
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Emulate Slack conversations.info."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _INVALID_AUTH

    from sqlalchemy import select

    from app.sandbox.models import SandboxConversation

    stmt = select(SandboxConversation).where(
        SandboxConversation.provider_id == provider.id,
        SandboxConversation.external_id == channel,
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if conv is None:
        return {"ok": False, "error": "channel_not_found"}
    return {"ok": True, "channel": format_channel(conv)}


@router.get("/conversations.history")
async def conversations_history(
    channel: str = Query(...),
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    limit: int = Query(default=100),
) -> dict[str, Any]:
    """Emulate Slack conversations.history."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _INVALID_AUTH

    from sqlalchemy import select

    from app.sandbox.models import SandboxConversation

    stmt = select(SandboxConversation).where(
        SandboxConversation.provider_id == provider.id,
        SandboxConversation.external_id == channel,
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if conv is None:
        return {"ok": False, "error": "channel_not_found"}

    messages, _ = await get_messages(db, provider.id, conversation_id=conv.id, limit=limit)
    formatted = [format_message(m, channel) for m in messages if not m.is_deleted]
    return {"ok": True, "messages": formatted, "has_more": False}


@router.get("/users.list")
async def users_list(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Emulate Slack users.list."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _INVALID_AUTH

    return {"ok": True, "members": [format_user(provider)]}


@router.get("/users.info")
async def users_info(
    user: str = Query(...),
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Emulate Slack users.info."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _INVALID_AUTH

    user_info = format_user(provider)
    if user != user_info["id"]:
        return {"ok": False, "error": "user_not_found"}
    return {"ok": True, "user": user_info}


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------


class SlackProvider(BaseSandboxProvider):
    """Slack Web API sandbox provider."""

    provider_name = "slack"

    def get_router(self) -> APIRouter:
        return router

    async def format_outbound_response(self, message: SandboxMessage) -> dict[str, Any]:
        channel = message.conversation_id or ""
        return format_message(message, channel)

    async def build_webhook_payload(
        self, message: SandboxMessage, event_type: str
    ) -> dict[str, Any]:
        # Need a provider to build the payload; fetch a minimal stand-in
        from app.sandbox.models import SandboxProvider as SPModel

        provider = SPModel(
            id=message.provider_id,
            user_id="",
            provider_type="slack",
            name="SlackBot",
        )
        return format_event_payload(message, provider)

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return "bot_token" in credentials

    def get_sandbox_url_hint(self, provider: Any) -> str:
        return "/sandbox/slack/api/"
