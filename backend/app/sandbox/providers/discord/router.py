"""Discord Bot API sandbox router and provider class."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.sandbox.models import SandboxConversation, SandboxMessage
from app.sandbox.providers.base import BaseSandboxProvider
from app.sandbox.providers.discord.formatter import (
    format_channel,
    format_message,
    format_webhook_payload,
)
from app.sandbox.providers.discord.schemas import (
    CreateMessageRequest,
    EditMessageRequest,
)
from app.sandbox.providers.discord.service import (
    get_bot_user,
    next_snowflake,
    resolve_bot_token,
)
from app.sandbox.service import (
    get_conversations,
    get_messages,
    get_or_create_conversation,
    store_message,
    update_raw_response,
)

logger = logging.getLogger("mailcue.sandbox.discord")

router = APIRouter(prefix="/sandbox/discord", tags=["Sandbox - Discord"])

_UNAUTHORIZED_RESPONSE: dict[str, Any] = {"message": "401: Unauthorized", "code": 0}


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


async def _resolve_bot(
    db: AsyncSession,
    authorization: str | None,
) -> Any:
    """Extract and resolve the Bot token from the Authorization header.

    Returns the ``SandboxProvider`` on success, raises ``HTTPException`` on
    failure with a Discord-style error response.
    """
    if authorization is None or not authorization.startswith("Bot "):
        raise HTTPException(status_code=401, detail=_UNAUTHORIZED_RESPONSE)
    token = authorization.removeprefix("Bot ").strip()
    provider = await resolve_bot_token(db, token)
    if provider is None:
        raise HTTPException(status_code=401, detail=_UNAUTHORIZED_RESPONSE)
    return provider


# ---------------------------------------------------------------------------
# Helper to find conversation by external_id (channel_id)
# ---------------------------------------------------------------------------


async def _get_conversation_by_channel(
    db: AsyncSession,
    provider_id: str,
    channel_id: str,
) -> SandboxConversation | None:
    """Resolve a channel_id to an existing conversation."""
    stmt = select(SandboxConversation).where(
        SandboxConversation.provider_id == provider_id,
        SandboxConversation.external_id == channel_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/v10/users/@me")
async def get_current_user(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return the bot user object."""
    provider = await _resolve_bot(db, authorization)
    return get_bot_user(provider)


@router.post("/api/v10/channels/{channel_id}/messages")
async def create_message(
    channel_id: str,
    body: CreateMessageRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Emulate Discord POST /channels/{channel_id}/messages."""
    provider = await _resolve_bot(db, authorization)

    conv = await get_or_create_conversation(
        db, provider.id, channel_id, f"discord-{channel_id}", "channel"
    )

    msg_id = next_snowflake(provider.id)
    embeds = body.embeds or []
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        provider.name,
        body.content,
        conversation_id=conv.id,
        content_type="text",
        external_id=msg_id,
        raw_request=body.model_dump(),
        metadata={
            "channel_id": channel_id,
            "embeds": embeds,
            "tts": body.tts,
        },
    )
    author = get_bot_user(provider)
    response = format_message(msg, channel_id, author)
    await update_raw_response(db, msg, response)
    return response


@router.get("/api/v10/channels/{channel_id}/messages")
async def list_messages(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Emulate Discord GET /channels/{channel_id}/messages."""
    provider = await _resolve_bot(db, authorization)

    conv = await _get_conversation_by_channel(db, provider.id, channel_id)
    if conv is None:
        return []

    messages, _total = await get_messages(db, provider.id, conversation_id=conv.id, limit=limit)
    author = get_bot_user(provider)
    return [format_message(m, channel_id, author) for m in messages]


@router.patch("/api/v10/channels/{channel_id}/messages/{message_id}")
async def edit_message(
    channel_id: str,
    message_id: str,
    body: EditMessageRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Emulate Discord PATCH /channels/{channel_id}/messages/{message_id}."""
    provider = await _resolve_bot(db, authorization)

    stmt = select(SandboxMessage).where(
        SandboxMessage.provider_id == provider.id,
        SandboxMessage.external_id == message_id,
    )
    result = await db.execute(stmt)
    msg = result.scalar_one_or_none()
    if msg is None:
        raise HTTPException(
            status_code=404,
            detail={"message": "Unknown Message", "code": 10008},
        )

    if body.content is not None:
        msg.content = body.content
    edited_ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    meta = {**msg.metadata_json, "edited_timestamp": edited_ts}
    if body.embeds is not None:
        meta["embeds"] = body.embeds
    msg.metadata_json = meta
    await db.commit()
    await db.refresh(msg)

    author = get_bot_user(provider)
    response = format_message(msg, channel_id, author)
    await update_raw_response(db, msg, response)
    return response


@router.delete(
    "/api/v10/channels/{channel_id}/messages/{message_id}",
    status_code=204,
    response_model=None,
)
async def delete_message(
    channel_id: str,
    message_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> None:
    """Emulate Discord DELETE /channels/{channel_id}/messages/{message_id}."""
    provider = await _resolve_bot(db, authorization)

    stmt = select(SandboxMessage).where(
        SandboxMessage.provider_id == provider.id,
        SandboxMessage.external_id == message_id,
    )
    result = await db.execute(stmt)
    msg = result.scalar_one_or_none()
    if msg is None:
        raise HTTPException(
            status_code=404,
            detail={"message": "Unknown Message", "code": 10008},
        )

    msg.is_deleted = True
    msg.content = ""
    await db.commit()


@router.get("/api/v10/channels/{channel_id}")
async def get_channel(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Emulate Discord GET /channels/{channel_id}."""
    provider = await _resolve_bot(db, authorization)

    conv = await _get_conversation_by_channel(db, provider.id, channel_id)
    if conv is None:
        raise HTTPException(
            status_code=404,
            detail={"message": "Unknown Channel", "code": 10003},
        )

    guild_id = conv.metadata_json.get("guild_id", "000000000000000000")
    return format_channel(conv, str(guild_id))


@router.get("/api/v10/guilds/{guild_id}/channels")
async def list_guild_channels(
    guild_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    """Emulate Discord GET /guilds/{guild_id}/channels."""
    provider = await _resolve_bot(db, authorization)

    conversations = await get_conversations(db, provider.id)
    return [
        format_channel(conv, guild_id)
        for conv in conversations
        if conv.metadata_json.get("guild_id", guild_id) == guild_id
    ]


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------


class DiscordProvider(BaseSandboxProvider):
    """Discord Bot API sandbox provider."""

    provider_name = "discord"

    def get_router(self) -> APIRouter:
        return router

    async def format_outbound_response(self, message: SandboxMessage) -> dict[str, Any]:
        channel_id = str(message.metadata_json.get("channel_id", "000000000000000000"))
        author: dict[str, Any] = message.metadata_json.get(
            "author",
            {
                "id": "000000000000000000",
                "username": message.sender,
                "discriminator": "0000",
                "avatar": None,
                "bot": True,
            },
        )
        return format_message(message, channel_id, author)

    async def build_webhook_payload(
        self, message: SandboxMessage, event_type: str
    ) -> dict[str, Any]:
        channel_id = str(message.metadata_json.get("channel_id", "000000000000000000"))
        guild_id = str(message.metadata_json.get("guild_id", "000000000000000000"))
        author: dict[str, Any] = message.metadata_json.get(
            "author",
            {
                "id": "000000000000000000",
                "username": message.sender,
                "discriminator": "0000",
                "avatar": None,
                "bot": False,
            },
        )
        return format_webhook_payload(message, channel_id, guild_id, author)

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return "bot_token" in credentials and "application_id" in credentials

    def get_sandbox_url_hint(self, provider: Any) -> str:
        return "/sandbox/discord/api/v10/channels/{channel_id}/messages"
