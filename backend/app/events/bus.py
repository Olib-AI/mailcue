"""In-process async event bus for SSE fan-out.

Provides a singleton ``event_bus`` that modules use to publish events
(e.g. ``email.received``, ``mailbox.created``).  SSE subscribers each
get an ``asyncio.Queue`` that receives copies of every published event.

Listeners can be registered via ``add_listener`` to react to specific
event types (e.g. forwarding rules processing on ``email.received``).

For multi-worker deployments (v2), replace the in-memory dict with
Redis pub/sub while keeping the same interface.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger("mailcue.events")

# Type alias for async event listeners.
EventListener = Callable[[str, dict[str, Any]], Awaitable[None]]


class EventBus:
    """Lightweight publish-subscribe bus backed by per-client asyncio queues.

    In addition to SSE fan-out, supports async *listeners* that are invoked
    after every publish.  Listeners are keyed by event type (or ``"*"`` for
    all events).
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, tuple[asyncio.Queue[dict[str, Any]], frozenset[str]]] = {}
        self._listeners: dict[str, list[EventListener]] = {}

    async def subscribe(
        self,
        client_id: str | None = None,
        *,
        allowed_mailboxes: set[str] | frozenset[str],
    ) -> tuple[str, asyncio.Queue[dict[str, Any]]]:
        """Register a new subscriber and return ``(client_id, queue)``.

        If *client_id* is ``None`` a UUID is generated automatically.
        """
        if client_id is None:
            client_id = str(uuid.uuid4())
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        normalized = frozenset(address.lower() for address in allowed_mailboxes)
        self._subscribers[client_id] = (queue, normalized)
        logger.debug("SSE subscriber connected: %s (total=%d)", client_id, len(self._subscribers))
        return client_id, queue

    def unsubscribe(self, client_id: str) -> None:
        """Remove a subscriber.  Safe to call with an unknown *client_id*."""
        self._subscribers.pop(client_id, None)
        logger.debug(
            "SSE subscriber disconnected: %s (total=%d)", client_id, len(self._subscribers)
        )

    def add_listener(self, event_type: str, callback: EventListener) -> None:
        """Register an async callback to be invoked when *event_type* is published.

        Use ``"*"`` to listen for all event types.  Listeners run after
        SSE fan-out completes and must not raise -- exceptions are logged
        but do not propagate.
        """
        self._listeners.setdefault(event_type, []).append(callback)
        logger.debug("Listener registered for event '%s'.", event_type)

    async def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast an event to all active subscribers and invoke listeners.

        Non-blocking: if a subscriber queue is full the event is dropped
        for that client rather than stalling the publisher.
        """
        message: dict[str, Any] = {"event": event_type, "data": data}
        logger.debug("Publishing event '%s' to %d subscribers", event_type, len(self._subscribers))

        stale: list[str] = []
        event_mailbox = self._event_mailbox(event_type, data)
        for cid, (queue, allowed_mailboxes) in self._subscribers.items():
            if event_mailbox is None or event_mailbox not in allowed_mailboxes:
                continue
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                stale.append(cid)
                logger.warning("Dropping event for slow subscriber %s", cid)

        # Prune stale clients whose queues are permanently full
        for cid in stale:
            self.unsubscribe(cid)

        # Invoke registered listeners (specific + wildcard).
        listeners = list(self._listeners.get(event_type, []))
        listeners.extend(self._listeners.get("*", []))
        for listener in listeners:
            try:
                await listener(event_type, data)
            except Exception:
                logger.exception("Listener for event '%s' raised an exception.", event_type)

    @staticmethod
    def _event_mailbox(event_type: str, data: dict[str, Any]) -> str | None:
        """Return the mailbox whose owner may receive an SSE event.

        Events without an attributable mailbox are intentionally not exposed to
        tenant streams. Internal listeners still receive every published event.
        """
        candidate: object | None
        if event_type == "email.sent":
            candidate = data.get("from")
        else:
            candidate = data.get("mailbox", data.get("address"))
        if isinstance(candidate, str) and "@" in candidate:
            return candidate.lower()
        return None

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Module-level singleton.
event_bus = EventBus()
