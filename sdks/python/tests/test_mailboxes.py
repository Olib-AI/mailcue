"""Tests for the ``mailboxes`` resource."""

from __future__ import annotations

import json

import httpx


def _mailbox_payload(address: str = "alice@example.com") -> dict[str, object]:
    return {
        "id": "01HXY",
        "address": address,
        "username": address.split("@")[0],
        "display_name": "Alice",
        "domain": address.split("@")[1],
        "is_active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "quota_mb": 500,
        "email_count": 3,
        "unread_count": 1,
    }


def test_list_mailboxes(make_client) -> None:  # type: ignore[no-untyped-def]
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"mailboxes": [_mailbox_payload()], "total": 1})

    client = make_client(handler)
    out = client.mailboxes.list()
    assert out.total == 1
    assert out.mailboxes[0].address == "alice@example.com"


def test_create_mailbox(make_client, captured_requests) -> None:  # type: ignore[no-untyped-def]
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json=_mailbox_payload())

    client = make_client(handler)
    mailbox = client.mailboxes.create("alice", "s3cret", domain="example.com", display_name="Alice")
    assert mailbox.address == "alice@example.com"

    payload = json.loads(captured_requests[0].content)
    assert payload == {
        "username": "alice",
        "password": "s3cret",
        "domain": "example.com",
        "display_name": "Alice",
    }


def test_mailbox_stats(make_client) -> None:  # type: ignore[no-untyped-def]
    body = {
        "mailbox_id": "01HXY",
        "address": "alice@example.com",
        "total_emails": 10,
        "unread_emails": 2,
        "total_size_bytes": 1024,
        "folders": [{"name": "INBOX", "message_count": 10, "unseen_count": 2}],
    }

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    client = make_client(handler)
    stats = client.mailboxes.stats("01HXY")
    assert stats.total_emails == 10
    assert stats.folders[0].name == "INBOX"


def test_create_mailbox_conflict_raises(make_client) -> None:  # type: ignore[no-untyped-def]
    import pytest

    from mailcue import ConflictError

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": "Mailbox already exists"})

    client = make_client(handler)
    with pytest.raises(ConflictError):
        client.mailboxes.create("alice", "pw")
