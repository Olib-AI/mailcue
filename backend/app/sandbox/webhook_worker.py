"""Async fire-and-forget webhook delivery for sandbox messages."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

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


async def deliver_webhooks(
    *,
    db_factory: async_sessionmaker,
    message: SandboxMessage,  # type: ignore[type-arg]
) -> None:
    """Fire-and-forget webhook delivery for a message."""
    async with db_factory() as db:
        # Get active webhook endpoints for this provider
        stmt = select(SandboxWebhookEndpoint).where(
            SandboxWebhookEndpoint.provider_id == message.provider_id,
            SandboxWebhookEndpoint.is_active.is_(True),
        )
        result = await db.execute(stmt)
        endpoints = list(result.scalars().all())

        if not endpoints:
            return

        # Reload the provider record to access provider_type
        provider_record = await db.get(SandboxProvider, message.provider_id)
        if not provider_record:
            return

        plugin = get_provider(provider_record.provider_type)

        for endpoint in endpoints:
            await _deliver_to_endpoint(db, endpoint, message, plugin)


async def _deliver_to_endpoint(
    db,
    endpoint: SandboxWebhookEndpoint,
    message: SandboxMessage,
    plugin: BaseSandboxProvider | None,
) -> None:
    """Attempt delivery to a single endpoint with exponential back-off."""
    event_type = "message.created"

    # Build payload using provider plugin or generic fallback
    if plugin:
        payload: dict = await plugin.build_webhook_payload(message, event_type)
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

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "MailCue-Sandbox/1.0",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        delivery = SandboxWebhookDelivery(
            endpoint_id=endpoint.id,
            message_id=message.id,
            event_type=event_type,
            payload=payload,
            attempt=attempt,
        )

        try:
            delivery_url = _rewrite_localhost_url(endpoint.url)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(delivery_url, json=payload, headers=headers)
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
        except Exception as exc:
            delivery.response_body = str(exc)[:2000]
            db.add(delivery)
            await db.commit()
            logger.warning("Webhook error %s (attempt %d): %s", endpoint.url, attempt, exc)

        if attempt < MAX_RETRIES:
            await asyncio.sleep(BACKOFF_BASE * (4 ** (attempt - 1)))
