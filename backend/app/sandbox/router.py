"""Management API router for the messaging sandbox."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.database import get_db
from app.dependencies import get_current_user
from app.sandbox.registry import get_provider
from app.sandbox.schemas import (
    ConversationResponse,
    MessageListResponse,
    MessageResponse,
    ProviderCreateRequest,
    ProviderResponse,
    ProviderUpdateRequest,
    SendRequest,
    SimulateRequest,
    WebhookDeliveryResponse,
    WebhookEndpointCreateRequest,
    WebhookEndpointResponse,
)
from app.sandbox.service import (
    create_provider,
    create_webhook_endpoint,
    delete_conversation,
    delete_message,
    delete_provider,
    delete_webhook_endpoint,
    get_conversations,
    get_messages,
    get_provider_by_id,
    get_providers,
    get_webhook_deliveries,
    get_webhook_endpoints,
    send_outbound,
    simulate_inbound,
    update_provider,
)

router = APIRouter(prefix="/sandbox", tags=["Sandbox"])


# ── Providers ─────────────────────────────────────────────────────


@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProviderResponse]:
    """List all sandbox providers for the current user."""
    providers = await get_providers(db, current_user.id)
    return [ProviderResponse.model_validate(p) for p in providers]


@router.post("/providers", response_model=ProviderResponse, status_code=201)
async def create_provider_endpoint(
    body: ProviderCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProviderResponse:
    """Create a new sandbox provider configuration."""
    provider = await create_provider(db, current_user.id, body)
    return ProviderResponse.model_validate(provider)


@router.get("/providers/{provider_id}")
async def get_provider_endpoint(
    provider_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single sandbox provider with its sandbox URL hint."""
    provider = await get_provider_by_id(db, provider_id, current_user.id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    data = ProviderResponse.model_validate(provider).model_dump()
    plugin = get_provider(provider.provider_type)
    data["sandbox_url"] = plugin.get_sandbox_url_hint(provider) if plugin else None
    return data


@router.put("/providers/{provider_id}", response_model=ProviderResponse)
async def update_provider_endpoint(
    provider_id: str,
    body: ProviderUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProviderResponse:
    """Update an existing sandbox provider."""
    provider = await update_provider(db, provider_id, current_user.id, body)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return ProviderResponse.model_validate(provider)


@router.delete("/providers/{provider_id}", status_code=204, response_model=None)
async def delete_provider_endpoint(
    provider_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a sandbox provider and all its data."""
    deleted = await delete_provider(db, provider_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Provider not found")


# ── Conversations ─────────────────────────────────────────────────


@router.get(
    "/providers/{provider_id}/conversations",
    response_model=list[ConversationResponse],
)
async def list_conversations(
    provider_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationResponse]:
    """List conversations for a provider."""
    provider = await get_provider_by_id(db, provider_id, current_user.id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    conversations = await get_conversations(db, provider_id)
    return [ConversationResponse.model_validate(c) for c in conversations]


@router.delete(
    "/providers/{provider_id}/conversations/{conversation_id}",
    status_code=204,
    response_model=None,
)
async def delete_conversation_endpoint(
    provider_id: str,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a conversation and all its messages."""
    provider = await get_provider_by_id(db, provider_id, current_user.id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    deleted = await delete_conversation(db, conversation_id, provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.get(
    "/providers/{provider_id}/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
)
async def list_conversation_messages(
    provider_id: str,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> MessageListResponse:
    """List messages in a specific conversation."""
    provider = await get_provider_by_id(db, provider_id, current_user.id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    messages, total = await get_messages(
        db, provider_id, conversation_id=conversation_id, limit=limit, offset=offset
    )
    return MessageListResponse(
        messages=[MessageResponse.model_validate(m) for m in messages],
        total=total,
    )


# ── Messages (cross-provider) ────────────────────────────────────


@router.get("/messages", response_model=MessageListResponse)
async def list_messages(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    provider_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> MessageListResponse:
    """List messages across providers (optionally filtered)."""
    if provider_id is not None:
        provider = await get_provider_by_id(db, provider_id, current_user.id)
        if provider is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        messages, total = await get_messages(db, provider_id, limit=limit, offset=offset)
    else:
        # Aggregate across all user providers
        providers = await get_providers(db, current_user.id)
        all_messages: list = []
        total = 0
        for p in providers:
            msgs, cnt = await get_messages(db, p.id, limit=limit, offset=offset)
            all_messages.extend(msgs)
            total += cnt
        # Re-sort and paginate the combined results
        all_messages.sort(key=lambda m: m.created_at)
        messages = all_messages[:limit]

    return MessageListResponse(
        messages=[MessageResponse.model_validate(m) for m in messages],
        total=total,
    )


@router.delete("/messages/{message_id}", status_code=204, response_model=None)
async def delete_message_endpoint(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a single message."""
    deleted = await delete_message(db, message_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Message not found")


# ── Simulate ──────────────────────────────────────────────────────


@router.post(
    "/providers/{provider_id}/simulate",
    response_model=MessageResponse,
    status_code=201,
)
async def simulate_inbound_endpoint(
    provider_id: str,
    body: SimulateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Simulate an inbound message from an external service."""
    try:
        message = await simulate_inbound(db, provider_id, current_user.id, body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MessageResponse.model_validate(message)


@router.post(
    "/providers/{provider_id}/send",
    response_model=MessageResponse,
    status_code=201,
)
async def send_message_endpoint(
    provider_id: str,
    body: SendRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Send an outbound message (user talking) and trigger webhooks."""
    try:
        message = await send_outbound(db, provider_id, current_user.id, body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MessageResponse.model_validate(message)


# ── Webhook endpoints ────────────────────────────────────────────


@router.post(
    "/providers/{provider_id}/webhooks",
    response_model=WebhookEndpointResponse,
    status_code=201,
)
async def create_webhook(
    provider_id: str,
    body: WebhookEndpointCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WebhookEndpointResponse:
    """Register a webhook endpoint for a provider."""
    provider = await get_provider_by_id(db, provider_id, current_user.id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    endpoint = await create_webhook_endpoint(db, provider_id, body)
    return WebhookEndpointResponse.model_validate(endpoint)


@router.get(
    "/providers/{provider_id}/webhooks",
    response_model=list[WebhookEndpointResponse],
)
async def list_webhooks(
    provider_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WebhookEndpointResponse]:
    """List webhook endpoints for a provider."""
    provider = await get_provider_by_id(db, provider_id, current_user.id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    endpoints = await get_webhook_endpoints(db, provider_id)
    return [WebhookEndpointResponse.model_validate(e) for e in endpoints]


@router.delete("/webhooks/{endpoint_id}", status_code=204, response_model=None)
async def delete_webhook(
    endpoint_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a webhook endpoint."""
    deleted = await delete_webhook_endpoint(db, endpoint_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")


# ── Webhook deliveries ───────────────────────────────────────────


@router.get(
    "/providers/{provider_id}/webhook-deliveries",
    response_model=list[WebhookDeliveryResponse],
)
async def list_webhook_deliveries(
    provider_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[WebhookDeliveryResponse]:
    """List recent webhook delivery records for a provider."""
    provider = await get_provider_by_id(db, provider_id, current_user.id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    deliveries = await get_webhook_deliveries(db, provider_id)
    return [WebhookDeliveryResponse.model_validate(d) for d in deliveries]
