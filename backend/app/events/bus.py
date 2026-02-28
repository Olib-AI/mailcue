"""In-process async event bus for SSE fan-out.

Provides a singleton ``event_bus`` that modules use to publish events
(e.g. ``email.received``, ``mailbox.created``).  SSE subscribers each
get an ``asyncio.Queue`` that receives copies of every published event.

For multi-worker deployments (v2), replace the in-memory dict with
Redis pub/sub while keeping the same interface.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

logger = logging.getLogger("mailcue.events")


class EventBus:
    """Lightweight publish-subscribe bus backed by per-client asyncio queues."""

    def __init__(self) -> None:
        self._subscribers: dict[str, asyncio.Queue[dict[str, Any]]] = {}

    async def subscribe(
        self, client_id: str | None = None
    ) -> tuple[str, asyncio.Queue[dict[str, Any]]]:
        """Register a new subscriber and return ``(client_id, queue)``.

        If *client_id* is ``None`` a UUID is generated automatically.
        """
        if client_id is None:
            client_id = str(uuid.uuid4())
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers[client_id] = queue
        logger.debug("SSE subscriber connected: %s (total=%d)", client_id, len(self._subscribers))
        return client_id, queue

    def unsubscribe(self, client_id: str) -> None:
        """Remove a subscriber.  Safe to call with an unknown *client_id*."""
        self._subscribers.pop(client_id, None)
        logger.debug(
            "SSE subscriber disconnected: %s (total=%d)", client_id, len(self._subscribers)
        )

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast an event to all active subscribers.

        Non-blocking: if a subscriber queue is full the event is dropped
        for that client rather than stalling the publisher.
        """
        message: dict[str, Any] = {"event": event_type, "data": data}
        logger.debug("Publishing event '%s' to %d subscribers", event_type, len(self._subscribers))

        stale: list[str] = []
        for cid, queue in self._subscribers.items():
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                stale.append(cid)
                logger.warning("Dropping event for slow subscriber %s", cid)

        # Prune stale clients whose queues are permanently full
        for cid in stale:
            self.unsubscribe(cid)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Module-level singleton.
event_bus = EventBus()
