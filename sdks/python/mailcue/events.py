"""Server-Sent Events client (sync + async) with auto-reconnect."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import AsyncIterator, Iterator, List, Optional

import httpx

from mailcue.exceptions import MailcueError, NetworkError
from mailcue.exceptions import TimeoutError as MailcueTimeoutError
from mailcue.transport import AsyncTransport, SyncTransport
from mailcue.types import Event

logger = logging.getLogger("mailcue.events")

_RECONNECT_BASE = 0.5
_RECONNECT_CAP = 30.0


def _parse_event(lines: List[str]) -> Optional[Event]:
    """Parse one SSE block of lines into an :class:`Event`."""
    event_type = "message"
    data_lines: List[str] = []
    event_id: Optional[str] = None
    retry: Optional[int] = None
    for line in lines:
        if not line or line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_type = value
        elif field == "data":
            data_lines.append(value)
        elif field == "id":
            event_id = value
        elif field == "retry":
            try:
                retry = int(value)
            except ValueError:
                retry = None
    if not data_lines and event_type == "message":
        return None
    raw_data = "\n".join(data_lines)
    payload: object = {}
    if raw_data:
        try:
            payload = json.loads(raw_data)
        except json.JSONDecodeError:
            payload = {"raw": raw_data}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    return Event(event_type=event_type, data=payload, id=event_id, retry=retry)


def _reconnect_delay(attempt: int) -> float:
    raw: float = min(_RECONNECT_CAP, _RECONNECT_BASE * float(2**attempt))
    jitter: float = raw * 0.2
    delay: float = raw + random.uniform(-jitter, jitter)
    return max(0.0, delay)


class SSEClient:
    """Synchronous SSE consumer with exponential-backoff reconnects."""

    def __init__(
        self,
        transport: SyncTransport,
        *,
        path: str = "/events/stream",
        reconnect: bool = True,
    ) -> None:
        self._transport = transport
        self._path = path
        self._reconnect = reconnect

    def __iter__(self) -> Iterator[Event]:
        return self.stream()

    def stream(self) -> Iterator[Event]:
        """Yield events forever (or until the server signals close).

        Example:
            >>> for event in client.events.stream():
            ...     print(event.event_type, event.data)
        """
        attempt = 0
        while True:
            try:
                yield from self._iterate_once()
                attempt = 0
                if not self._reconnect:
                    return
            except (NetworkError, MailcueTimeoutError, httpx.HTTPError) as exc:
                if not self._reconnect:
                    raise
                delay = _reconnect_delay(attempt)
                logger.warning(
                    "SSE connection lost (%s); reconnecting in %.2fs",
                    exc,
                    delay,
                )
                time.sleep(delay)
                attempt += 1

    def _iterate_once(self) -> Iterator[Event]:
        response = self._transport.open_stream(
            "GET",
            self._path,
            headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"},
            timeout=None,
        )
        try:
            buffer: List[str] = []
            for line in response.iter_lines():
                if line == "":
                    event = _parse_event(buffer)
                    buffer = []
                    if event is not None:
                        yield event
                else:
                    buffer.append(line)
            if buffer:
                event = _parse_event(buffer)
                if event is not None:
                    yield event
        finally:
            response.close()


class AsyncSSEClient:
    """Asynchronous SSE consumer with exponential-backoff reconnects."""

    def __init__(
        self,
        transport: AsyncTransport,
        *,
        path: str = "/events/stream",
        reconnect: bool = True,
    ) -> None:
        self._transport = transport
        self._path = path
        self._reconnect = reconnect

    def __aiter__(self) -> AsyncIterator[Event]:
        return self.stream()

    async def stream(self) -> AsyncIterator[Event]:
        """Yield events forever (or until the server signals close)."""
        attempt = 0
        while True:
            try:
                async for event in self._iterate_once():
                    attempt = 0
                    yield event
                if not self._reconnect:
                    return
            except (NetworkError, MailcueTimeoutError, httpx.HTTPError) as exc:
                if not self._reconnect:
                    raise
                delay = _reconnect_delay(attempt)
                logger.warning(
                    "SSE connection lost (%s); reconnecting in %.2fs",
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                attempt += 1
            except MailcueError:
                raise

    async def _iterate_once(self) -> AsyncIterator[Event]:
        response = await self._transport.open_stream(
            "GET",
            self._path,
            headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"},
            timeout=None,
        )
        try:
            buffer: List[str] = []
            async for line in response.aiter_lines():
                if line == "":
                    event = _parse_event(buffer)
                    buffer = []
                    if event is not None:
                        yield event
                else:
                    buffer.append(line)
            if buffer:
                event = _parse_event(buffer)
                if event is not None:
                    yield event
        finally:
            await response.aclose()
