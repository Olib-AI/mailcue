"""Core service functions for the messaging sandbox."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from weakref import WeakSet

from sqlalchemy import delete, func, select

from app.sandbox.models import (
    SandboxConversation,
    SandboxMessage,
    SandboxProvider,
    SandboxWebhookDelivery,
    SandboxWebhookEndpoint,
)
from app.sandbox.schemas import (
    WebhookEndpointCreateRequest,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.sandbox.schemas import (
        ProviderCreateRequest,
        ProviderUpdateRequest,
        SendRequest,
        SimulateRequest,
    )

logger = logging.getLogger("mailcue.sandbox")


# ── Provider CRUD ────────────────────────────────────────────────


async def get_providers(db: AsyncSession, user_id: str) -> list[SandboxProvider]:
    """Return all providers belonging to a user."""
    stmt = select(SandboxProvider).where(SandboxProvider.user_id == user_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_provider_by_id(
    db: AsyncSession, provider_id: str, user_id: str
) -> SandboxProvider | None:
    """Return a single provider if owned by the user."""
    stmt = select(SandboxProvider).where(
        SandboxProvider.id == provider_id,
        SandboxProvider.user_id == user_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_provider(
    db: AsyncSession, user_id: str, data: ProviderCreateRequest
) -> SandboxProvider:
    """Create a new sandbox provider configuration."""
    provider = SandboxProvider(
        user_id=user_id,
        provider_type=data.provider_type,
        name=data.name,
        credentials=data.credentials,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider


async def update_provider(
    db: AsyncSession, provider_id: str, user_id: str, data: ProviderUpdateRequest
) -> SandboxProvider | None:
    """Update an existing provider, returning None if not found."""
    provider = await get_provider_by_id(db, provider_id, user_id)
    if provider is None:
        return None
    if data.name is not None:
        provider.name = data.name
    if data.credentials is not None:
        provider.credentials = data.credentials
    if data.is_active is not None:
        provider.is_active = data.is_active
    provider.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(provider)
    return provider


async def delete_provider(db: AsyncSession, provider_id: str, user_id: str) -> bool:
    """Delete a provider and all its data, returning True if it existed."""
    provider = await get_provider_by_id(db, provider_id, user_id)
    if provider is None:
        return False
    await db.delete(provider)
    await db.commit()
    return True


# ── Credential resolution ────────────────────────────────────────


async def resolve_provider_by_credential(
    db: AsyncSession,
    provider_type: str,
    credential_key: str,
    credential_value: str,
) -> SandboxProvider | None:
    """Find an active provider whose JSON credentials contain the given key/value."""
    stmt = select(SandboxProvider).where(
        SandboxProvider.provider_type == provider_type,
        SandboxProvider.is_active.is_(True),
    )
    result = await db.execute(stmt)
    providers = result.scalars().all()
    for provider in providers:
        if provider.credentials.get(credential_key) == credential_value:
            return provider
    return None


async def store_message(
    db: AsyncSession,
    provider_id: str,
    direction: str,
    sender: str,
    content: str | None,
    *,
    conversation_id: str | None = None,
    content_type: str = "text",
    external_id: str | None = None,
    raw_request: dict | None = None,
    raw_response: dict | None = None,
    metadata: dict | None = None,
) -> SandboxMessage:
    """Persist a sandbox message and return the ORM instance."""
    msg = SandboxMessage(
        provider_id=provider_id,
        conversation_id=conversation_id,
        direction=direction,
        sender=sender,
        content=content,
        content_type=content_type,
        external_id=external_id,
        raw_request=raw_request or {},
        raw_response=raw_response or {},
        metadata_json=metadata or {},
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def update_raw_response(
    db: AsyncSession,
    msg: SandboxMessage,
    raw_response: dict,
) -> None:
    """Update the raw_response field on a stored message."""
    msg.raw_response = raw_response
    await db.commit()


async def get_or_create_conversation(
    db: AsyncSession,
    provider_id: str,
    external_id: str,
    name: str | None,
    conv_type: str,
) -> SandboxConversation:
    """Return an existing conversation or create a new one."""
    stmt = select(SandboxConversation).where(
        SandboxConversation.provider_id == provider_id,
        SandboxConversation.external_id == external_id,
    )
    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    if conversation is not None:
        return conversation
    conversation = SandboxConversation(
        provider_id=provider_id,
        external_id=external_id,
        name=name,
        conversation_type=conv_type,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def get_conversations(
    db: AsyncSession,
    provider_id: str,
) -> list[SandboxConversation]:
    """Return all conversations for a provider."""
    stmt = select(SandboxConversation).where(SandboxConversation.provider_id == provider_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_conversation(
    db: AsyncSession,
    conversation_id: str,
    provider_id: str,
) -> bool:
    """Delete a conversation and its messages, returning True if it existed."""
    stmt = select(SandboxConversation).where(
        SandboxConversation.id == conversation_id,
        SandboxConversation.provider_id == provider_id,
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()
    if conv is None:
        return False
    await db.delete(conv)
    await db.commit()
    return True


async def delete_message(
    db: AsyncSession,
    message_id: str,
) -> bool:
    """Delete a single message, returning True if it existed."""
    stmt = select(SandboxMessage).where(SandboxMessage.id == message_id)
    result = await db.execute(stmt)
    msg = result.scalar_one_or_none()
    if msg is None:
        return False
    await db.delete(msg)
    await db.commit()
    return True


async def get_messages(
    db: AsyncSession,
    provider_id: str,
    conversation_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SandboxMessage], int]:
    """Return paginated messages and a total count."""
    base = select(SandboxMessage).where(SandboxMessage.provider_id == provider_id)
    count_base = (
        select(func.count())
        .select_from(SandboxMessage)
        .where(SandboxMessage.provider_id == provider_id)
    )
    if conversation_id is not None:
        base = base.where(SandboxMessage.conversation_id == conversation_id)
        count_base = count_base.where(SandboxMessage.conversation_id == conversation_id)
    total_result = await db.execute(count_base)
    total = total_result.scalar_one()
    stmt = base.order_by(SandboxMessage.created_at.asc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def create_webhook_endpoint(
    db: AsyncSession,
    provider_id: str,
    data: dict | WebhookEndpointCreateRequest,
) -> SandboxWebhookEndpoint:
    """Create and return a new webhook endpoint."""
    if not isinstance(data, dict):
        data = data.model_dump()
    endpoint = SandboxWebhookEndpoint(
        provider_id=provider_id,
        url=data.get("url", ""),
        secret=data.get("secret"),
        event_types=data.get("event_types", []),
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)
    return endpoint


async def get_webhook_endpoints(
    db: AsyncSession,
    provider_id: str,
) -> list[SandboxWebhookEndpoint]:
    """Return all webhook endpoints for a provider."""
    stmt = select(SandboxWebhookEndpoint).where(SandboxWebhookEndpoint.provider_id == provider_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_webhook_endpoint(
    db: AsyncSession,
    endpoint_id: str,
) -> bool:
    """Delete a webhook endpoint, returning True if it existed."""
    stmt = delete(SandboxWebhookEndpoint).where(SandboxWebhookEndpoint.id == endpoint_id)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0  # type: ignore[union-attr]


async def get_webhook_deliveries(
    db: AsyncSession,
    provider_id: str,
    limit: int = 50,
) -> list[SandboxWebhookDelivery]:
    """Return recent webhook delivery records for a provider."""
    stmt = (
        select(SandboxWebhookDelivery)
        .join(SandboxWebhookEndpoint)
        .where(SandboxWebhookEndpoint.provider_id == provider_id)
        .order_by(SandboxWebhookDelivery.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ── Simulate ─────────────────────────────────────────────────────


async def simulate_inbound(
    db: AsyncSession,
    provider_id: str,
    user_id: str,
    data: SimulateRequest,
) -> SandboxMessage:
    """Simulate an inbound message from an external sender."""
    provider = await get_provider_by_id(db, provider_id, user_id)
    if provider is None:
        raise ValueError("Provider not found")

    # Resolve or create conversation
    conversation_id: str | None = data.conversation_id
    if conversation_id is None:
        ext_id = f"sim-{data.sender}"
        conv = await get_or_create_conversation(
            db,
            provider_id,
            ext_id,
            data.conversation_name or f"Chat with {data.sender}",
            "direct",
        )
        conversation_id = conv.id

    msg = await store_message(
        db,
        provider_id,
        "inbound",
        data.sender,
        data.content,
        conversation_id=conversation_id,
        content_type=data.content_type,
        metadata=data.metadata,
    )

    # Fire webhooks for inbound messages (bot receives user messages)
    _fire_webhooks(msg)
    return msg


async def send_outbound(
    db: AsyncSession,
    provider_id: str,
    user_id: str,
    data: SendRequest,
) -> SandboxMessage:
    """Send an outbound message (user talking) and trigger webhooks."""
    provider = await get_provider_by_id(db, provider_id, user_id)
    if provider is None:
        raise ValueError("Provider not found")

    # Resolve or create conversation
    conversation_id: str | None = data.conversation_id
    if conversation_id is None:
        ext_id = f"user-{data.sender}"
        conv = await get_or_create_conversation(
            db,
            provider_id,
            ext_id,
            data.conversation_name or f"Chat with {data.sender}",
            "direct",
        )
        conversation_id = conv.id

    msg = await store_message(
        db,
        provider_id,
        "outbound",
        data.sender,
        data.content,
        conversation_id=conversation_id,
        content_type=data.content_type,
        metadata=data.metadata,
    )

    # Fire webhooks — user message triggers bot's webhook endpoint
    _fire_webhooks(msg)
    return msg


_background_tasks: WeakSet[asyncio.Task] = WeakSet()  # prevent GC of fire-and-forget tasks


def _fire_webhooks(msg: SandboxMessage) -> None:
    """Schedule async webhook delivery for a message."""
    from app.database import AsyncSessionLocal
    from app.sandbox.webhook_worker import deliver_webhooks

    task = asyncio.create_task(deliver_webhooks(db_factory=AsyncSessionLocal, message=msg))
    _background_tasks.add(task)
