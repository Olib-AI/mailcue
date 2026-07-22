"""Tests for SendEmailRequest bcc_addresses, GPG public key auto-import, and GPG router external key access."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.emails.schemas import SendEmailRequest
from app.gpg import service as gpg_service
from app.gpg.schemas import GpgKeyResponse


def test_send_email_request_accepts_bcc_addresses() -> None:
    """SendEmailRequest schema should contain bcc_addresses attribute without raising AttributeError."""
    req = SendEmailRequest(
        from_address="sender@example.com",
        to_addresses=["to@example.com"],
        cc_addresses=["cc@example.com"],
        bcc_addresses=["bcc@example.com"],
        subject="Test Subject",
        body="Test Body",
    )
    assert req.bcc_addresses == ["bcc@example.com"]
    assert req.to_addresses == ["to@example.com"]


@pytest.mark.asyncio
async def test_extract_and_import_keys_from_email_extracts_armored_blocks(_engine_and_session, monkeypatch) -> None:
    """extract_and_import_keys_from_email extracts PGP public key blocks from raw bytes and imports them."""
    _engine, factory = _engine_and_session
    sample_key = (
        "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
        "Version: Test\n\n"
        "mQENBF...fakekey...\n"
        "-----END PGP PUBLIC KEY BLOCK-----"
    )
    email_text = f"From: sender@example.com\nSubject: Key Attached\n\nHere is my public key:\n\n{sample_key}"
    raw_bytes = email_text.encode("utf-8")

    async def fake_import_key(req, db):
        return GpgKeyResponse(
            id="test-id",
            mailbox_address=req.mailbox_address or "sender@example.com",
            fingerprint="1234567890ABCDEF1234567890ABCDEF12345678",
            key_id="90ABCDEF12345678",
            uid_name="Sender",
            uid_email="sender@example.com",
            algorithm="RSA",
            key_length=2048,
            created_at=datetime.now(UTC),
            expires_at=None,
            is_private=False,
            public_key_armor=req.armored_key,
            is_active=True,
        )

    monkeypatch.setattr(gpg_service, "import_key", fake_import_key)

    async with factory() as session:
        imported = await gpg_service.extract_and_import_keys_from_email(
            raw_bytes, "sender@example.com", session
        )
        assert len(imported) == 1
        assert imported[0].mailbox_address == "sender@example.com"

