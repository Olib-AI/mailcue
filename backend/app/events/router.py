"""SSE (Server-Sent Events) endpoint for real-time notifications.

Emits events such as ``email.received``, ``email.sent``, ``email.deleted``,
``mailbox.created``, and ``mailbox.deleted``.  A heartbeat comment is sent
every 30 seconds to keep the connection alive through proxies.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.auth import scopes
from app.database import get_db
from app.dependencies import AuthContext, get_auth, require_scope
from app.events.bus import event_bus
from app.mailboxes.models import Mailbox

logger = logging.getLogger("mailcue.events")

router = APIRouter(prefix="/events", tags=["Events"])

_HEARTBEAT_INTERVAL_SECONDS = 30


async def _event_generator(
    client_id: str,
    queue: asyncio.Queue[dict[str, object]],
) -> AsyncGenerator[dict[str, str], None]:
    """Yield SSE-formatted dicts from the subscriber queue.

    Sends a ``:heartbeat`` comment every 30 s when no data events arrive.
    On disconnect the subscriber is automatically unregistered.
    """
    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    queue.get(),
                    timeout=_HEARTBEAT_INTERVAL_SECONDS,
                )
                yield {
                    "event": str(message.get("event", "message")),
                    "data": json.dumps(message.get("data", {})),
                }
            except TimeoutError:
                # Heartbeat as a named event so clients can distinguish it.
                yield {"event": "heartbeat", "data": ""}
    finally:
        event_bus.unsubscribe(client_id)


@router.get(
    "/stream",
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def event_stream(
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> EventSourceResponse:
    """Open an SSE stream for the authenticated user.

    Events are broadcast from the in-process event bus.  The stream
    sends a heartbeat comment every 30 seconds to keep the TCP
    connection alive through proxies and load balancers.
    """
    stmt = select(Mailbox.address).where(
        Mailbox.user_id == auth.user.id,
        Mailbox.is_active.is_(True),
    )
    owned_mailboxes = set((await db.execute(stmt)).scalars().all())
    allowed = {address for address in owned_mailboxes if auth.mailbox_allowed(address)}
    client_id, queue = await event_bus.subscribe(allowed_mailboxes=allowed)
    logger.info(
        "SSE stream opened for user '%s' (client=%s)",
        auth.user.username,
        client_id,
    )
    return EventSourceResponse(
        _event_generator(client_id, queue),
        media_type="text/event-stream",
    )
