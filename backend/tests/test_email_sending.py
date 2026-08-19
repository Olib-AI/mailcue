"""Regression tests for outbound Sent copies and PGP/MIME rendering."""

from __future__ import annotations

from email import message_from_bytes, policy
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.emails import service as email_service
from app.emails.parser import parse_email
from app.emails.schemas import SendEmailRequest
from app.gpg import service as gpg_service


@pytest.mark.asyncio
async def test_send_email_does_not_append_a_second_sent_copy(monkeypatch) -> None:
    smtp_send = AsyncMock()
    publish = AsyncMock()

    async def unexpected_imap_connect(_address: str):
        raise AssertionError("send_email must rely on Postfix sender_bcc_maps for Sent")

    monkeypatch.setattr(email_service.aiosmtplib, "send", smtp_send)
    monkeypatch.setattr(email_service.event_bus, "publish", publish)
    monkeypatch.setattr(email_service, "_imap_connect", unexpected_imap_connect)

    request = SendEmailRequest(
        from_address="sender@example.com",
        to_addresses=["recipient@example.net"],
        subject="One Sent copy",
        body="Hello",
        body_type="plain",
    )

    message_id = await email_service.send_email(request)

    assert message_id
    smtp_send.assert_awaited_once()
    publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_signed_message_retains_ui_bodies_and_valid_mime_structure(monkeypatch) -> None:
    original = MIMEMultipart("alternative", policy=policy.SMTP)
    original["From"] = "Sender <sender@example.com>"
    original["To"] = "recipient@example.net"
    original["Subject"] = "Signed message"
    original["Date"] = "Sun, 02 Aug 2026 01:59:31 +0000"
    original["Message-ID"] = "<signed@example.com>"
    original["Reply-To"] = "reply@example.com"
    original["References"] = "<root@example.com>"
    original["X-Mailer"] = "MailCue/1.0"
    original.attach(MIMEText("Readable plain body", "plain", "utf-8", policy=policy.SMTP))
    original.attach(MIMEText("<p>Readable HTML body</p>", "html", "utf-8", policy=policy.SMTP))

    fake_gpg = SimpleNamespace()
    signed_content: list[bytes] = []

    def fake_sign(data: bytes, **_kwargs):
        signed_content.append(data)
        return SimpleNamespace(data=b"detached-signature", stderr="")

    fake_gpg.sign = fake_sign

    async def fake_key(_sender: str, _db, *, user_id: str):
        assert user_id == "user-1"
        return SimpleNamespace(is_private=True, fingerprint="ABCDEF")

    monkeypatch.setattr(gpg_service, "get_key_for_address", fake_key)
    monkeypatch.setattr(gpg_service, "_get_gpg", lambda: fake_gpg)

    raw = await gpg_service.sign_message(
        original.as_bytes(policy=policy.SMTP),
        "sender@example.com",
        object(),
        user_id="user-1",
    )

    wrapped = message_from_bytes(raw, policy=policy.SMTP)
    assert wrapped.get_content_type() == "multipart/signed"
    assert len(wrapped.get_all("MIME-Version", [])) == 1
    assert wrapped["Reply-To"] == "reply@example.com"
    assert wrapped["References"] == "<root@example.com>"
    assert wrapped["X-Mailer"] == "MailCue/1.0"

    content_part = wrapped.get_payload(0)
    assert content_part["From"] is None
    assert content_part["To"] is None
    assert content_part["Subject"] is None
    assert signed_content == [content_part.as_bytes(policy=policy.SMTP)]

    detail = parse_email(raw)
    assert detail.is_signed is True
    assert detail.text_body == "Readable plain body"
    assert detail.html_body == "<p>Readable HTML body</p>"


# ── From header: display name resolution ─────────────────────────


def _sent_from_header(smtp_send) -> str:
    """The From header of the message handed to SMTP."""
    return smtp_send.await_args.args[0]["From"]


async def _send_with(monkeypatch, *, from_name: str = "", display_name=None, db=None):
    smtp_send = AsyncMock()
    monkeypatch.setattr(email_service.aiosmtplib, "send", smtp_send)
    monkeypatch.setattr(email_service.event_bus, "publish", AsyncMock())

    if display_name is not None:

        async def fake_lookup(address: str, _db):
            return SimpleNamespace(display_name=display_name)

        monkeypatch.setattr("app.mailboxes.service.get_mailbox_by_address", fake_lookup)

    request = SendEmailRequest(
        from_address="agent@example.com",
        from_name=from_name,
        to_addresses=["recipient@example.net"],
        subject="Display name",
        body="Hello",
        body_type="plain",
    )
    await email_service.send_email(request, db=db)
    return _sent_from_header(smtp_send)


@pytest.mark.asyncio
async def test_from_name_on_the_request_wins(monkeypatch) -> None:
    header = await _send_with(
        monkeypatch, from_name="Explicit Name", display_name="Mailbox Name", db=object()
    )
    assert header == "Explicit Name <agent@example.com>"


@pytest.mark.asyncio
async def test_falls_back_to_the_mailbox_display_name(monkeypatch) -> None:
    """A name someone chose on the mailbox should reach the recipient."""
    header = await _send_with(monkeypatch, display_name="Olib AI Agent", db=object())
    assert header == "Olib AI Agent <agent@example.com>"


@pytest.mark.asyncio
async def test_default_display_name_is_not_used(monkeypatch) -> None:
    """Mailboxes default display_name to the local part. `"agent" <agent@...>`
    is noisier than the bare address, so it is treated as unset."""
    header = await _send_with(monkeypatch, display_name="agent", db=object())
    assert header == "agent@example.com"


@pytest.mark.asyncio
async def test_no_db_session_sends_bare_address(monkeypatch) -> None:
    header = await _send_with(monkeypatch, db=None)
    assert header == "agent@example.com"


@pytest.mark.asyncio
async def test_lookup_failure_never_blocks_a_send(monkeypatch) -> None:
    smtp_send = AsyncMock()
    monkeypatch.setattr(email_service.aiosmtplib, "send", smtp_send)
    monkeypatch.setattr(email_service.event_bus, "publish", AsyncMock())

    async def boom(_address: str, _db):
        raise RuntimeError("database is down")

    monkeypatch.setattr("app.mailboxes.service.get_mailbox_by_address", boom)

    request = SendEmailRequest(
        from_address="agent@example.com",
        to_addresses=["recipient@example.net"],
        subject="Still sends",
        body="Hello",
        body_type="plain",
    )
    assert await email_service.send_email(request, db=object())
    assert _sent_from_header(smtp_send) == "agent@example.com"
