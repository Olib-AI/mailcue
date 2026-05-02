"""Tests for the ``emails`` resource."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import httpx


def test_send_basic_html(make_client, captured_requests) -> None:  # type: ignore[no-untyped-def]
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"message_id": "<abc@local>", "status": "queued"})

    client = make_client(handler)
    result = client.emails.send(
        from_="hello@example.com",
        to=["user@example.com"],
        subject="Welcome",
        html="<h1>Hi</h1>",
    )
    assert result.message_id == "<abc@local>"

    request = captured_requests[0]
    payload = json.loads(request.content)
    assert payload["from_address"] == "hello@example.com"
    assert payload["to_addresses"] == ["user@example.com"]
    assert payload["subject"] == "Welcome"
    assert payload["body"] == "<h1>Hi</h1>"
    assert payload["body_type"] == "html"
    assert payload["sign"] is False
    assert payload["encrypt"] is False
    assert "attachments" not in payload


def test_send_plain_text_with_cc_and_attachment(make_client, captured_requests) -> None:  # type: ignore[no-untyped-def]
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"message_id": "<x@local>"})

    client = make_client(handler)
    raw_pdf = b"%PDF-1.4 fake"
    client.emails.send(
        from_="ops@example.com",
        to=["user@example.com"],
        cc=["cc@example.com"],
        bcc=["bcc@example.com"],
        subject="Invoice",
        text="Plain body",
        reply_to="ops@example.com",
        attachments=[
            {
                "filename": "i.pdf",
                "content_type": "application/pdf",
                "content": raw_pdf,
            }
        ],
    )

    payload = json.loads(captured_requests[0].content)
    assert payload["body"] == "Plain body"
    assert payload["body_type"] == "plain"
    assert payload["cc_addresses"] == ["cc@example.com"]
    assert payload["bcc_addresses"] == ["bcc@example.com"]
    assert payload["reply_to"] == "ops@example.com"
    assert len(payload["attachments"]) == 1
    encoded = payload["attachments"][0]["data"]
    assert base64.b64decode(encoded) == raw_pdf


def test_send_requires_body() -> None:
    import pytest

    from mailcue import Mailcue

    client = Mailcue(api_key="mc_x", base_url="http://test.local")
    try:
        with pytest.raises(ValueError):
            client.emails.send(
                from_="a@b.com",
                to=["c@d.com"],
                subject="x",
            )
    finally:
        client.close()


def test_list_emails(make_client, captured_requests) -> None:  # type: ignore[no-untyped-def]
    response_body = {
        "total": 1,
        "page": 1,
        "page_size": 50,
        "emails": [
            {
                "uid": "1",
                "mailbox": "user@example.com",
                "from_address": "alice@x.com",
                "to_addresses": ["user@example.com"],
                "subject": "Hi",
                "has_attachments": False,
                "is_read": False,
                "preview": "preview",
                "date": "2026-01-01T00:00:00+00:00",
            }
        ],
        "has_more": False,
    }

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_body)

    client = make_client(handler)
    inbox = client.emails.list(mailbox="user@example.com")
    assert inbox.total == 1
    assert inbox.emails[0].uid == "1"
    assert inbox.emails[0].date == datetime(2026, 1, 1, tzinfo=timezone.utc)

    request = captured_requests[0]
    assert request.url.params["mailbox"] == "user@example.com"
    assert request.url.params["folder"] == "INBOX"
    assert request.url.params["page"] == "1"


def test_get_email_404(make_client) -> None:  # type: ignore[no-untyped-def]
    import pytest

    from mailcue import NotFoundError

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Email '99' not found"})

    client = make_client(handler)
    with pytest.raises(NotFoundError) as excinfo:
        client.emails.get("99", mailbox="user@example.com")
    assert excinfo.value.status_code == 404
    assert "not found" in excinfo.value.message.lower()


def test_get_raw_returns_bytes(make_client) -> None:  # type: ignore[no-untyped-def]
    raw = b"From: a@b.com\r\nSubject: hi\r\n\r\nbody"

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=raw, headers={"content-type": "message/rfc822"})

    client = make_client(handler)
    out = client.emails.get_raw("1", mailbox="user@example.com")
    assert out == raw


def test_delete_email(make_client, captured_requests) -> None:  # type: ignore[no-untyped-def]
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    client = make_client(handler)
    client.emails.delete("1", mailbox="user@example.com")

    request = captured_requests[0]
    assert request.method == "DELETE"
    assert request.url.path == "/api/v1/emails/1"


async def test_async_send(make_async_client) -> None:  # type: ignore[no-untyped-def]
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"message_id": "<async@local>"})

    client, _http = make_async_client(handler)
    async with client:
        result = await client.emails.send(
            from_="a@b.com",
            to=["c@d.com"],
            subject="Hi",
            text="hello",
        )
    assert result.message_id == "<async@local>"
