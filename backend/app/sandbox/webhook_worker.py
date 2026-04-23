"""Async fire-and-forget webhook delivery for sandbox messages.

The worker wires a stored :class:`SandboxMessage` up to every registered,
active :class:`SandboxWebhookEndpoint` for its provider.  Payload shape and
content-type come from the provider plugin's ``build_webhook_payload`` +
``webhook_content_type`` hooks, and headers are signed by the plugin's
``build_webhook_signer`` hook — so each provider delivers in the exact wire
format its real service uses (Twilio form-encoded + ``X-Twilio-Signature``,
Bandwidth JSON array + HTTP Basic, Vonage JSON + Bearer-JWT, Plivo form +
``X-Plivo-Signature-V3``, Telnyx JSON + Ed25519 signature).
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.sandbox.models import (
    SandboxMessage,
    SandboxProvider,
    SandboxWebhookDelivery,
    SandboxWebhookEndpoint,
)
from app.sandbox.registry import get_provider

if TYPE_CHECKING:
    from app.sandbox.providers.base import BaseSandboxProvider

logger = logging.getLogger("mailcue.sandbox.webhook")

MAX_RETRIES = 3
BACKOFF_BASE = 1  # seconds

# Inside Docker, localhost:8088 (host-mapped port) is unreachable.
# Rewrite to localhost:80 (internal nginx) so webhooks to the built-in
# HTTP Bin and other local endpoints work out of the box.
_LOCALHOST_PORT_RE = re.compile(
    r"^(https?://)(localhost|127\.0\.0\.1):(\d+)(/.*)?$", re.IGNORECASE
)


def _rewrite_localhost_url(url: str) -> str:
    """Rewrite localhost URLs to use the internal nginx port (80)."""
    m = _LOCALHOST_PORT_RE.match(url)
    if m:
        scheme, host, _port, path = m.groups()
        return f"{scheme}{host}:80{path or '/'}"
    return url


def _serialise_payload(
    payload: dict[str, Any] | list[Any],
    content_type: str,
) -> tuple[bytes, str]:
    """Serialise ``payload`` to bytes + Content-Type header value."""
    if content_type == "form":
        if not isinstance(payload, dict):
            # Form-encoded webhooks must be dicts; fall back to JSON.
            logger.warning(
                "Non-dict payload with content_type='form' — falling back to JSON",
            )
            return _json.dumps(payload).encode("utf-8"), "application/json"
        body = urlencode({k: ("" if v is None else str(v)) for k, v in payload.items()}).encode(
            "utf-8"
        )
        return body, "application/x-www-form-urlencoded"
    return _json.dumps(payload).encode("utf-8"), "application/json"


async def deliver_webhooks(
    *,
    db_factory: async_sessionmaker[AsyncSession],
    message: SandboxMessage,
) -> None:
    """Fire-and-forget webhook delivery for a message.

    Early-returns silently when the provider has no registered endpoints —
    keeps a zero-cost wire path for users who haven't configured webhook URLs.
    """
    async with db_factory() as db:
        stmt = select(SandboxWebhookEndpoint).where(
            SandboxWebhookEndpoint.provider_id == message.provider_id,
            SandboxWebhookEndpoint.is_active.is_(True),
        )
        result = await db.execute(stmt)
        endpoints = list(result.scalars().all())

        if not endpoints:
            return

        provider_record = await db.get(SandboxProvider, message.provider_id)
        if provider_record is None:
            return

        plugin = get_provider(provider_record.provider_type)

        for endpoint in endpoints:
            await _deliver_to_endpoint(
                db=db,
                endpoint=endpoint,
                message=message,
                provider_record=provider_record,
                plugin=plugin,
            )


async def _deliver_to_endpoint(
    *,
    db: AsyncSession,
    endpoint: SandboxWebhookEndpoint,
    message: SandboxMessage,
    provider_record: SandboxProvider,
    plugin: BaseSandboxProvider | None,
) -> None:
    """Attempt delivery to a single endpoint with exponential back-off."""
    event_type = "message.received" if message.direction == "inbound" else "message.created"

    if plugin is not None:
        payload: dict[str, Any] | list[Any] = await plugin.build_webhook_payload(
            message, event_type
        )
        content_type_label = plugin.webhook_content_type(message, event_type)
    else:
        payload = {
            "event": event_type,
            "message": {
                "id": message.id,
                "direction": message.direction,
                "sender": message.sender,
                "content": message.content,
            },
        }
        content_type_label = "json"

    body_bytes, content_type_header = _serialise_payload(payload, content_type_label)
    base_headers: dict[str, str] = {
        "Content-Type": content_type_header,
        "User-Agent": "MailCue-Sandbox/1.0",
    }

    delivery_url = _rewrite_localhost_url(endpoint.url)

    # Resolve the provider-native signer (if any).  Signers must see the
    # target URL the receiver will verify against — the fase webhook handler
    # recomputes its signature from the request URL, so we must feed the
    # signer the *public* URL (post-localhost rewrite) for signature parity.
    signer = None
    if plugin is not None:
        signer = plugin.build_webhook_signer(
            message=message,
            provider_record=provider_record,
            url=delivery_url,
            payload_body=body_bytes,
        )
    if signer is not None:
        base_headers = await signer(base_headers, body_bytes)

    for attempt in range(1, MAX_RETRIES + 1):
        delivery = SandboxWebhookDelivery(
            endpoint_id=endpoint.id,
            message_id=message.id,
            event_type=event_type,
            payload=payload if isinstance(payload, dict) else {"__array__": payload},
            attempt=attempt,
        )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(delivery_url, content=body_bytes, headers=base_headers)
                delivery.status_code = resp.status_code
                delivery.response_body = resp.text[:2000]
                delivery.delivered_at = datetime.now(UTC)
                db.add(delivery)
                await db.commit()

                if resp.status_code < 400:
                    logger.info(
                        "Webhook delivered to %s (attempt %d, status %d)",
                        endpoint.url,
                        attempt,
                        resp.status_code,
                    )
                    return

                logger.warning(
                    "Webhook failed %s (attempt %d, status %d)",
                    endpoint.url,
                    attempt,
                    resp.status_code,
                )
        except Exception as exc:  # retry any network error / provider failure
            delivery.response_body = str(exc)[:2000]
            db.add(delivery)
            await db.commit()
            logger.warning("Webhook error %s (attempt %d): %s", endpoint.url, attempt, exc)

        if attempt < MAX_RETRIES:
            await asyncio.sleep(BACKOFF_BASE * (4 ** (attempt - 1)))
