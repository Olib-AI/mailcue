"""WhatsApp Business Cloud API sandbox router and provider class."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.sandbox.models import SandboxMessage
from app.sandbox.providers.base import BaseSandboxProvider
from app.sandbox.providers.whatsapp.formatter import (
    format_message_response,
    format_webhook_payload,
)
from app.sandbox.providers.whatsapp.schemas import (
    MarkReadRequest,
    SendMessageRequest,
    SetWebhookRequest,
)
from app.sandbox.providers.whatsapp.service import (
    get_phone_number_id,
    next_message_id,
    resolve_access_token,
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

logger = logging.getLogger("mailcue.sandbox.whatsapp")

router = APIRouter(prefix="/sandbox/whatsapp", tags=["Sandbox - WhatsApp"])


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


async def _resolve_bearer(
    db: AsyncSession,
    authorization: str | None,
) -> Any:
    """Extract and resolve the Bearer token from the Authorization header.

    Returns the ``SandboxProvider`` on success, raises ``HTTPException`` on
    failure so callers get a proper WhatsApp-style error response.
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid OAuth access token.",
                    "type": "OAuthException",
                    "code": 190,
                    "fbtrace_id": "mailcue_sandbox",
                }
            },
        )
    token = authorization.removeprefix("Bearer ").strip()
    provider = await resolve_access_token(db, token)
    if provider is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid OAuth access token.",
                    "type": "OAuthException",
                    "code": 190,
                    "fbtrace_id": "mailcue_sandbox",
                }
            },
        )
    return provider


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.api_route("/v1/{phone_number_id}", methods=["GET"])
async def get_phone_number_info(
    phone_number_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return phone number metadata (sandbox stub)."""
    provider = await _resolve_bearer(db, authorization)
    configured_phone = get_phone_number_id(provider)

    display_phone = provider.credentials.get("display_phone_number", configured_phone)
    return {
        "verified_name": provider.name,
        "display_phone_number": str(display_phone),
        "id": phone_number_id,
        "quality_rating": "GREEN",
    }


@router.post("/v1/{phone_number_id}/messages")
async def send_message(
    phone_number_id: str,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Emulate WhatsApp Cloud API sendMessage.

    Supports text, image, document, audio, video, and template message types.
    """
    provider = await _resolve_bearer(db, authorization)

    # Determine content and content_type from the request
    content: str = ""
    content_type: str = body.type

    match body.type:
        case "text":
            content = body.text.body if body.text else ""
        case "image":
            content = body.image.caption or "[image]" if body.image else "[image]"
            content_type = "image"
        case "document":
            content = body.document.caption or "[document]" if body.document else "[document]"
            content_type = "document"
        case "audio":
            content = "[audio]"
            content_type = "audio"
        case "video":
            content = body.video.caption or "[video]" if body.video else "[video]"
            content_type = "video"
        case "template":
            tmpl_name = body.template.name if body.template else "unknown"
            content = f"[template:{tmpl_name}]"
            content_type = "template"
        case _:
            content = f"[{body.type}]"

    conv = await get_or_create_conversation(
        db, provider.id, body.to, f"WhatsApp {body.to}", "direct"
    )
    msg_id = next_message_id(provider.id)
    msg = await store_message(
        db,
        provider.id,
        "outbound",
        provider.name,
        content,
        conversation_id=conv.id,
        content_type=content_type,
        external_id=msg_id,
        raw_request=body.model_dump(),
        metadata={"to": body.to, "phone_number_id": phone_number_id},
    )
    response = format_message_response(msg, phone_number_id)
    await update_raw_response(db, msg, response)
    return response


@router.put("/v1/{phone_number_id}/messages/{message_id}")
async def mark_as_read(
    phone_number_id: str,
    message_id: str,
    body: MarkReadRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Emulate WhatsApp Cloud API mark-as-read."""
    await _resolve_bearer(db, authorization)

    return {"success": True}


@router.get("/v1/{phone_number_id}/messages")
async def list_messages(
    phone_number_id: str,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    limit: int = 50,
) -> dict[str, Any]:
    """List messages for a phone number (non-standard sandbox convenience endpoint)."""
    provider = await _resolve_bearer(db, authorization)
    messages, total = await get_messages(db, provider.id, limit=limit)

    formatted: list[dict[str, object]] = []
    for msg in messages:
        formatted.append(
            {
                "id": msg.external_id or msg.id,
                "from": msg.sender,
                "to": msg.metadata_json.get("to", phone_number_id),
                "type": msg.content_type,
                "timestamp": str(int(msg.created_at.timestamp()) if msg.created_at else 0),
                "direction": msg.direction,
                "text": {"body": msg.content} if msg.content_type == "text" else None,
                "content": msg.content,
            }
        )

    return {
        "messaging_product": "whatsapp",
        "messages": formatted,
        "total": total,
    }


@router.post("/v1/webhook")
async def set_webhook(
    body: SetWebhookRequest,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Register a webhook URL (sandbox convenience endpoint)."""
    provider = await _resolve_bearer(db, authorization)

    # Remove existing webhooks first
    existing = await get_webhook_endpoints(db, provider.id)
    for ep in existing:
        await delete_webhook_endpoint(db, ep.id)

    await create_webhook_endpoint(
        db,
        provider.id,
        {
            "url": body.url,
            "verify_token": body.verify_token,
            "event_types": ["messages"],
        },
    )
    return {"success": True}


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------


class WhatsAppProvider(BaseSandboxProvider):
    """WhatsApp Business Cloud API sandbox provider."""

    provider_name = "whatsapp"

    def get_router(self) -> APIRouter:
        return router

    async def format_outbound_response(self, message: SandboxMessage) -> dict[str, Any]:
        phone_number_id = message.metadata_json.get("phone_number_id", "000000000000000")
        return format_message_response(message, str(phone_number_id))

    async def build_webhook_payload(
        self, message: SandboxMessage, event_type: str
    ) -> dict[str, Any]:
        phone_number_id = message.metadata_json.get("phone_number_id", "000000000000000")

        # We need the provider for the webhook payload but only have message here.
        # Build a minimal structure; the formatter handles missing fields gracefully.
        # Construct a lightweight proxy with the fields the formatter needs.
        class _ProviderProxy:
            def __init__(self, msg: SandboxMessage) -> None:
                self.id = msg.provider_id
                self.name = msg.metadata_json.get("provider_name", "WhatsApp Sandbox")
                self.credentials: dict[str, Any] = msg.metadata_json.get(
                    "provider_credentials", {}
                )

        proxy = _ProviderProxy(message)
        return format_webhook_payload(
            message,
            str(phone_number_id),
            proxy,  # type: ignore[arg-type]
        )

    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        return "access_token" in credentials and "phone_number_id" in credentials

    def get_sandbox_url_hint(self, provider: Any) -> str:
        phone_id = provider.credentials.get("phone_number_id", "{phone_number_id}")
        return f"/sandbox/whatsapp/v1/{phone_id}/messages"
