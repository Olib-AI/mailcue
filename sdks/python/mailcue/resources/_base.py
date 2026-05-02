"""Base classes for API resource bindings."""

from __future__ import annotations

from mailcue.transport import AsyncTransport, SyncTransport


class SyncResource:
    """Resource backed by a synchronous transport."""

    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport


class AsyncResource:
    """Resource backed by an asynchronous transport."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport
