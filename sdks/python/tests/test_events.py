"""Tests for SSE event parsing."""

from __future__ import annotations

import json

import httpx

from mailcue.events import _parse_event


def test_parse_event_with_named_type_and_json_data() -> None:
    block = ["event: email.received", 'data: {"uid": "1", "mailbox": "u@e.com"}']
    event = _parse_event(block)
    assert event is not None
    assert event.event_type == "email.received"
    assert event.data == {"uid": "1", "mailbox": "u@e.com"}


def test_parse_event_multiline_data() -> None:
    block = ["event: email.sent", "data: line1", "data: line2"]
    event = _parse_event(block)
    assert event is not None
    # multiline data is joined with newlines and parsed as JSON if possible.
    assert event.data == {"raw": "line1\nline2"}


def test_parse_event_skips_comments_and_empty() -> None:
    block = [": heartbeat comment", "", "event: heartbeat"]
    event = _parse_event(block)
    assert event is not None
    assert event.event_type == "heartbeat"


def test_parse_event_empty_block_returns_none() -> None:
    assert _parse_event([": just a comment"]) is None


def test_sse_stream_yields_events_then_returns() -> None:
    """End-to-end: the iterator parses a finite SSE response and stops."""
    body = b'event: email.received\ndata: {"uid": "1"}\n\nevent: heartbeat\ndata: \n\n'

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    from mailcue import Mailcue

    client = Mailcue(
        api_key="mc_test",
        base_url="http://test.local",
        http_client=http_client,
        max_retries=0,
    )
    try:
        from mailcue.events import SSEClient

        sse = SSEClient(client._transport, reconnect=False)
        events = list(sse.stream())
    finally:
        client.close()

    assert len(events) == 2
    assert events[0].event_type == "email.received"
    assert events[0].data == {"uid": "1"}
    assert events[1].event_type == "heartbeat"


def test_parse_event_with_id_and_retry() -> None:
    block = ["event: email.deleted", "id: abc-123", "retry: 5000", 'data: {"uid": "9"}']
    event = _parse_event(block)
    assert event is not None
    assert event.id == "abc-123"
    assert event.retry == 5000
    assert event.data == {"uid": "9"}


def test_parse_event_data_only_defaults_to_message_type() -> None:
    block = ['data: {"hello": "world"}']
    event = _parse_event(block)
    assert event is not None
    assert event.event_type == "message"
    assert json.dumps(event.data) == '{"hello": "world"}'
