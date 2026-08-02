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
