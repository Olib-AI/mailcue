"""Mattermost API v4 sandbox router and provider class."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.sandbox.models import SandboxMessage
from app.sandbox.providers.base import BaseSandboxProvider
from app.sandbox.providers.mattermost.formatter import (
    format_channel,
    format_post,
    format_user,
)
from app.sandbox.providers.mattermost.schemas import CreatePostRequest
from app.sandbox.providers.mattermost.service import (
    generate_post_id,
    resolve_access_token,
)
from app.sandbox.service import (
    get_messages,
    get_or_create_conversation,
    store_message,
    update_raw_response,
)

logger = logging.getLogger("mailcue.sandbox.mattermost")

router = APIRouter(prefix="/sandbox/mattermost/api/v4", tags=["Sandbox - Mattermost"])

_UNAUTHORIZED = JSONResponse(
    status_code=401,
    content={
        "id": "api.context.session_expired.app_error",
        "message": "Invalid or missing token",
        "status_code": 401,
    },
)


async def _resolve_from_header(
    db: AsyncSession,
    authorization: str | None,
) -> Any:
    """Extract bearer token and resolve provider."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return await resolve_access_token(db, token)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.api_route("/", methods=["GET", "POST"])
async def mattermost_index() -> Any:
    """Index route showing available Mattermost API v4 sandbox endpoints."""
    return {
        "description": "MailCue Mattermost API v4 Sandbox",
        "endpoints": [
            "POST   /posts",
            "GET    /posts/{id}",
            "PUT    /posts/{id}",
            "DELETE /posts/{id}",
            "GET    /channels",
            "GET    /channels/{id}",
            "GET    /channels/{id}/posts",
            "GET    /users/me",
        ],
    }


@router.post("/posts")
async def create_post(
    body: CreatePostRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Emulate Mattermost create post."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _UNAUTHORIZED

    conv = await get_or_create_conversation(
        db, provider.id, body.channel_id, body.channel_id, "channel"
    )
    post_id = generate_post_id()
    user_info = format_user(provider)
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        user_info["id"],
        body.message,
        conversation_id=conv.id,
        content_type="text",
        external_id=post_id,
        raw_request=body.model_dump(),
        metadata={"root_id": body.root_id} if body.root_id else None,
    )
    response = format_post(msg, body.channel_id)
    await update_raw_response(db, msg, response)
    return response


@router.get("/posts/{post_id}")
async def get_post(
    post_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Emulate Mattermost get post."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _UNAUTHORIZED

    messages, _ = await get_messages(db, provider.id, limit=1000)
    for msg in messages:
        if msg.external_id == post_id:
            channel_id = msg.conversation_id or ""
            return format_post(msg, channel_id)

    return JSONResponse(
        status_code=404,
        content={
            "id": "store.sql_post.get.app_error",
            "message": "Post not found",
            "status_code": 404,
        },
    )


@router.put("/posts/{post_id}")
async def update_post(
    post_id: str,
    body: CreatePostRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Emulate Mattermost update post."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _UNAUTHORIZED

    conv = await get_or_create_conversation(
        db, provider.id, body.channel_id, body.channel_id, "channel"
    )
    user_info = format_user(provider)
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        user_info["id"],
        body.message,
        conversation_id=conv.id,
        content_type="text",
        external_id=post_id,
        raw_request=body.model_dump(),
        metadata={"edited": True},
    )
    response = format_post(msg, body.channel_id)
    await update_raw_response(db, msg, response)
    return response


@router.delete("/posts/{post_id}")
async def delete_post(
    post_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Emulate Mattermost delete post."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _UNAUTHORIZED

    messages, _ = await get_messages(db, provider.id, limit=1000)
    for msg in messages:
        if msg.external_id == post_id:
            msg.is_deleted = True
            await db.commit()
            return {"status": "OK"}

    return JSONResponse(
        status_code=404,
        content={
            "id": "store.sql_post.get.app_error",
            "message": "Post not found",
            "status_code": 404,
        },
    )


@router.get("/channels")
async def list_channels(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Emulate Mattermost list channels."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _UNAUTHORIZED

    from sqlalchemy import select

    from app.sandbox.models import SandboxConversation

    stmt = select(SandboxConversation).where(SandboxConversation.provider_id == provider.id)
    result = await db.execute(stmt)
    convs = result.scalars().all()
    return [format_channel(c) for c in convs]


@router.get("/channels/{channel_id}")
async def get_channel(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Emulate Mattermost get channel."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _UNAUTHORIZED

    from sqlalchemy import select

    from app.sandbox.models import SandboxConversation

    stmt = select(SandboxConversation).where(
        SandboxConversation.provider_id == provider.id,
        SandboxConversation.external_id == channel_id,
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if conv is None:
        return JSONResponse(
            status_code=404,
            content={
                "id": "store.sql_channel.get.app_error",
                "message": "Channel not found",
                "status_code": 404,
            },
        )
    return format_channel(conv)


@router.get("/channels/{channel_id}/posts")
async def get_channel_posts(
    channel_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Emulate Mattermost get channel posts."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _UNAUTHORIZED

    from sqlalchemy import select

    from app.sandbox.models import SandboxConversation

    stmt = select(SandboxConversation).where(
        SandboxConversation.provider_id == provider.id,
        SandboxConversation.external_id == channel_id,
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if conv is None:
        return {"order": [], "posts": {}}

    messages, _ = await get_messages(db, provider.id, conversation_id=conv.id)
    posts: dict[str, Any] = {}
    order: list[str] = []
    for msg in messages:
        if msg.is_deleted:
            continue
        post = format_post(msg, channel_id)
        post_id = post["id"]
        posts[post_id] = post
        order.append(post_id)

    return {"order": order, "posts": posts}


@router.get("/users/me")
async def get_current_user(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> Any:
    """Emulate Mattermost get current user."""
    provider = await _resolve_from_header(db, authorization)
    if provider is None:
        return _UNAUTHORIZED

    return format_user(provider)


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------


class MattermostProvider(BaseSandboxProvider):
    """Mattermost API v4 sandbox provider."""

    provider_name = "mattermost"

    def get_router(self) -> APIRouter:
        return router

    async def format_outbound_response(self, message: SandboxMessage) -> dict[str, Any]:
        channel_id = message.conversation_id or ""
        return format_post(message, channel_id)

    async def build_webhook_payload(
        self, message: SandboxMessage, event_type: str
    ) -> dict[str, Any]:
        channel_id = message.conversation_id or ""
        post = format_post(message, channel_id)
        return {"event": event_type, "data": {"post": post}}

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return "access_token" in credentials

    def get_sandbox_url_hint(self, provider: Any) -> str:
        return "/sandbox/mattermost/api/v4/"
