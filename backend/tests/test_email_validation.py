"""Unit and integration tests for email address validation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiosmtplib
import dns.resolver
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.emails.disposable import (
    is_disposable_domain,
    load_cached_domains,
    update_disposable_domains,
)
from app.emails.validation import (
    validate_dns,
    validate_mailbox,
    validate_syntax,
)
from app.mailboxes.models import Mailbox

OWNER_ID = "perm-owner-id-validation"
MB_A = "a-validation@mailcue.local"
MB_B = "b-validation@mailcue.local"


@pytest.fixture()
async def perm_client(_engine_and_session: Any) -> AsyncIterator[tuple[AsyncClient, Any]]:
    """Client with real auth; yields (client, session_factory)."""
    _engine, factory = _engine_and_session

    from app.database import get_db
    from app.main import app

    async with factory() as session:
        session.add(
            User(
                id=OWNER_ID,
                username="permowner",
                email=MB_A,
                hashed_password="unused",
                is_admin=True,
                is_active=True,
            )
        )
        for addr in (MB_A, MB_B):
            session.add(
                Mailbox(
                    address=addr,
                    domain="mailcue.local",
                    user_id=OWNER_ID,
                )
            )
        await session.commit()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac, factory
    app.dependency_overrides.clear()


# ── 1. Syntax Validation Tests ───────────────────────────────────


def test_syntax_validation() -> None:
    # Valid syntax
    assert validate_syntax("user@mailcue.io").is_valid is True
    assert validate_syntax("first.last@domain.co.uk").is_valid is True
    assert validate_syntax("user+tag@domain.company").is_valid is True
    assert validate_syntax("a@b.cd").is_valid is True
    assert validate_syntax("xn--tda@xn--diseo-rta.com").is_valid is True  # IDN

    # Invalid syntax
    assert validate_syntax("").is_valid is False
    assert validate_syntax("missing-at").is_valid is False
    assert validate_syntax("double@@at.com").is_valid is False
    assert validate_syntax("space in@email.com").is_valid is False
    assert validate_syntax("user@").is_valid is False
    assert validate_syntax("@domain.com").is_valid is False
    assert validate_syntax("user@domain").is_valid is False  # Missing dot in domain
    assert validate_syntax("user@.domain.com").is_valid is False
    assert validate_syntax("user@domain..com").is_valid is False
    assert validate_syntax("user@domain.-com").is_valid is False
    assert validate_syntax("user@domain.c").is_valid is False  # TLD too short

    # Length restrictions
    assert validate_syntax("a" * 65 + "@mailcue.io").is_valid is False  # Local part > 64
    assert (
        validate_syntax(
            "user@" + "a" * 63 + "." + "b" * 63 + "." + "c" * 63 + "." + "d" * 63
        ).is_valid
        is False
    )  # Domain > 255
    assert validate_syntax("user@" + "a" * 64 + ".com").is_valid is False  # Label > 63


# ── 2. DNS Verification Tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_dns_validation_success() -> None:
    # Mock answers for MX, NS, A
    mock_mx = [MagicMock(preference=10, exchange=dns.name.from_text("mail.example.com."))]
    mock_ns = [MagicMock(target=dns.name.from_text("ns1.example.com."))]
    mock_a = [MagicMock(address="192.0.2.1")]

    def mock_resolve(qname: str, rdtype: str) -> list[MagicMock]:
        if rdtype == "MX":
            return mock_mx
        if rdtype == "NS":
            return mock_ns
        if rdtype == "A":
            return mock_a
        raise dns.resolver.NoAnswer()

    with patch("app.emails.validation._resolver.resolve", side_effect=mock_resolve):
        res = await validate_dns("mailcue.io")
        assert res.is_valid is True
        assert res.has_mx is True
        assert res.has_ns is True
        assert res.has_a is True
        assert res.mx_records == ["10 mail.example.com."]
        assert res.ns_records == ["ns1.example.com."]
        assert res.a_records == ["192.0.2.1"]
        assert res.error is None


@pytest.mark.asyncio
async def test_dns_validation_no_mx_fallback_a() -> None:
    mock_ns = [MagicMock(target=dns.name.from_text("ns1.example.com."))]
    mock_a = [MagicMock(address="192.0.2.1")]

    def mock_resolve(qname: str, rdtype: str) -> list[MagicMock]:
        if rdtype == "NS":
            return mock_ns
        if rdtype == "A":
            return mock_a
        raise dns.resolver.NoAnswer()

    with patch("app.emails.validation._resolver.resolve", side_effect=mock_resolve):
        res = await validate_dns("mailcue.io")
        assert res.is_valid is True  # Valid because A and NS exist
        assert res.has_mx is False
        assert res.has_ns is True
        assert res.has_a is True
        assert res.mx_records == []
        assert res.error is None


@pytest.mark.asyncio
async def test_dns_validation_nxdomain() -> None:
    with patch("app.emails.validation._resolver.resolve", side_effect=dns.resolver.NXDOMAIN()):
        res = await validate_dns("nonexistent.com")
        assert res.is_valid is False
        assert res.has_mx is False
        assert res.has_ns is False
        assert res.has_a is False
        assert "No Name Servers" in (res.error or "")


# ── 3. SMTP Mailbox Probe Tests ─────────────────────────────────


@pytest.mark.asyncio
@patch("aiosmtplib.SMTP")
async def test_validate_mailbox_success(mock_smtp_class: MagicMock) -> None:
    mock_smtp = AsyncMock()
    mock_smtp.is_connected = True
    mock_smtp.close = MagicMock()
    mock_smtp_class.return_value = mock_smtp

    # Setup connection, ehlo, mail response, and rcpt response (250 OK)
    mock_smtp.mail.return_value = (250, "Sender OK")
    mock_smtp.rcpt.side_effect = [
        (250, "Recipient OK"),  # Target email
        (550, "No such user"),  # Catch-all check (rejected, meaning NOT catch-all)
    ]

    res = await validate_mailbox(
        domain="example.com",
        mx_records=["10 mail.example.com."],
        target_email="test@example.com",
        sender_email="sender@mailcue.local",
    )

    assert res.is_valid is True
    assert res.smtp_code == 250
    assert res.catch_all is False
    assert res.error is None


@pytest.mark.asyncio
@patch("aiosmtplib.SMTP")
async def test_validate_mailbox_catch_all(mock_smtp_class: MagicMock) -> None:
    mock_smtp = AsyncMock()
    mock_smtp.is_connected = True
    mock_smtp.close = MagicMock()
    mock_smtp_class.return_value = mock_smtp

    mock_smtp.mail.return_value = (250, "Sender OK")
    mock_smtp.rcpt.side_effect = [
        (250, "Recipient OK"),  # Target email
        (250, "Recipient OK"),  # Catch-all check accepts random address too!
    ]

    res = await validate_mailbox(
        domain="example.com",
        mx_records=["10 mail.example.com."],
        target_email="test@example.com",
        sender_email="sender@mailcue.local",
    )

    assert res.is_valid is True
    assert res.catch_all is True


@pytest.mark.asyncio
@patch("aiosmtplib.SMTP")
async def test_validate_mailbox_rejected(mock_smtp_class: MagicMock) -> None:
    mock_smtp = AsyncMock()
    mock_smtp.is_connected = True
    mock_smtp.close = MagicMock()
    mock_smtp_class.return_value = mock_smtp

    mock_smtp.connect.side_effect = aiosmtplib.SMTPResponseException(550, "No such mailbox here")

    res = await validate_mailbox(
        domain="example.com",
        mx_records=["10 mail.example.com."],
        target_email="test@example.com",
        sender_email="sender@mailcue.local",
    )

    assert res.is_valid is False
    assert res.smtp_code == 550
    assert "No such mailbox" in (res.smtp_response or "")


@pytest.mark.asyncio
@patch("aiosmtplib.SMTP")
async def test_validate_mailbox_connection_timeout(mock_smtp_class: MagicMock) -> None:
    mock_smtp = AsyncMock()
    mock_smtp.is_connected = True
    mock_smtp.close = MagicMock()
    mock_smtp_class.return_value = mock_smtp
    mock_smtp.connect.side_effect = OSError("Connection timed out")

    res = await validate_mailbox(
        domain="example.com",
        mx_records=["10 mail.example.com."],
        target_email="test@example.com",
        sender_email="sender@mailcue.local",
    )

    assert res.is_valid is None  # Connection blocked/timed out
    assert "Connection timed out" in (res.error or "")


# ── 4. Disposable Domain Check Tests ─────────────────────────────


def test_disposable_domain_check() -> None:
    assert is_disposable_domain("mailinator.com") is True
    assert is_disposable_domain("yopmail.com") is True
    assert is_disposable_domain("gmail.com") is False
    assert is_disposable_domain("mailcue.io") is False


@pytest.mark.asyncio
async def test_update_disposable_domains(tmp_path: pytest.TempPathFactory) -> None:
    # Set cache path to a temporary file
    test_cache = tmp_path / "disposable_test.txt"
    with patch("app.emails.disposable.get_cache_file_path", return_value=test_cache):
        # Mock successful fetch response containing a couple of test domains
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "# comments\n\ntemp-domain.com\nother-temp.org\n"

        async def mock_get(*args: object, **kwargs: object) -> MagicMock:
            return mock_response

        with patch("httpx.AsyncClient.get", side_effect=mock_get):
            await update_disposable_domains()

        assert test_cache.exists()
        content = test_cache.read_text(encoding="utf-8")
        assert "temp-domain.com" in content
        assert "other-temp.org" in content

        # Check in-memory update
        assert is_disposable_domain("temp-domain.com") is True
        assert is_disposable_domain("other-temp.org") is True

        # Test reloading cache
        load_cached_domains()
        assert is_disposable_domain("temp-domain.com") is True

        # Restore fallback domains
        import app.emails.disposable
        from app.emails.disposable import FALLBACK_DOMAINS

        app.emails.disposable._loaded_domains = set(FALLBACK_DOMAINS)


# ── 5. API Endpoint Integration Tests ─────────────────────────────


@pytest.mark.asyncio
async def test_validate_api_endpoint_invalid_syntax(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/emails/validate", json={"email": "bademail"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "bademail"
    assert data["is_valid"] is False
    assert data["status"] == "invalid"
    assert data["syntax"]["is_valid"] is False


@pytest.mark.asyncio
async def test_validate_api_endpoint_success(client: AsyncClient) -> None:
    mock_mx = [MagicMock(preference=10, exchange=dns.name.from_text("mail.example.com."))]
    mock_ns = [MagicMock(target=dns.name.from_text("ns1.example.com."))]
    mock_a = [MagicMock(address="192.0.2.1")]

    def mock_resolve(qname: str, rdtype: str) -> list[MagicMock]:
        if rdtype == "MX":
            return mock_mx
        if rdtype == "NS":
            return mock_ns
        if rdtype == "A":
            return mock_a
        raise dns.resolver.NoAnswer()

    mock_smtp = AsyncMock()
    mock_smtp.is_connected = True
    mock_smtp.close = MagicMock()
    mock_smtp.mail.return_value = (250, "Sender OK")
    mock_smtp.rcpt.side_effect = [
        (250, "Recipient OK"),  # Target email
        (550, "No such user"),  # Not catch-all
    ]

    with (
        patch("app.emails.validation._resolver.resolve", side_effect=mock_resolve),
        patch("aiosmtplib.SMTP", return_value=mock_smtp),
    ):
        resp = await client.post("/api/v1/emails/validate", json={"email": "good@mailcue.io"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "good@mailcue.io"
        assert data["is_valid"] is True
        assert data["status"] == "valid"
        assert data["syntax"]["is_valid"] is True
        assert data["dns"]["is_valid"] is True
        assert data["mailbox"]["is_valid"] is True
        assert data["mailbox"]["catch_all"] is False
        assert data["disposable"]["is_disposable"] is False


@pytest.mark.asyncio
async def test_validate_api_endpoint_disposable(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/emails/validate", json={"email": "test@mailinator.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@mailinator.com"
    assert data["is_valid"] is False
    assert data["status"] == "disposable"
    assert data["disposable"]["is_disposable"] is True


# ── 6. Scope Gating Tests ────────────────────────────────────────


async def _make_key_local(
    session: AsyncSession,
    *,
    scopes: list[str],
    allowed_mailboxes: list[str] | None = None,
) -> str:
    from app.auth.models import APIKey
    from app.auth.service import api_key_prefix, generate_api_key, hash_password

    raw = generate_api_key()
    session.add(
        APIKey(
            user_id=OWNER_ID,
            key_hash=hash_password(raw),
            name="test-key",
            prefix=api_key_prefix(raw),
            scopes=scopes,
            allowed_mailboxes=allowed_mailboxes,
        )
    )
    await session.commit()
    return raw


@pytest.mark.asyncio
async def test_api_key_permissions_gating(perm_client: tuple[AsyncClient, Any]) -> None:
    client, factory = perm_client

    # Create key WITHOUT email:validate scope
    async with factory() as session:
        key_no_scope = await _make_key_local(session, scopes=["email:read"])

    # Test request fails with 403
    headers = {"X-API-Key": key_no_scope}
    resp = await client.post(
        "/api/v1/emails/validate",
        json={"email": "test@mailcue.io"},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "missing the required 'email:validate' permission" in resp.json()["detail"]

    # Create key WITH email:validate scope
    async with factory() as session:
        key_with_scope = await _make_key_local(session, scopes=["email:validate"])

    # Mock DNS/SMTP to avoid real network calls
    mock_mx = [MagicMock(preference=10, exchange=dns.name.from_text("mail.example.com."))]
    mock_ns = [MagicMock(target=dns.name.from_text("ns1.example.com."))]
    mock_a = [MagicMock(address="192.0.2.1")]

    def mock_resolve(qname: str, rdtype: str) -> list[MagicMock]:
        if rdtype == "MX":
            return mock_mx
        if rdtype == "NS":
            return mock_ns
        if rdtype == "A":
            return mock_a
        raise dns.resolver.NoAnswer()

    mock_smtp = AsyncMock()
    mock_smtp.is_connected = True
    mock_smtp.close = MagicMock()
    mock_smtp.mail.return_value = (250, "Sender OK")
    mock_smtp.rcpt.side_effect = [
        (250, "Recipient OK"),
        (550, "No such user"),
    ]

    with (
        patch("app.emails.validation._resolver.resolve", side_effect=mock_resolve),
        patch("aiosmtplib.SMTP", return_value=mock_smtp),
    ):
        headers = {"X-API-Key": key_with_scope}
        resp = await client.post(
            "/api/v1/emails/validate",
            json={"email": "test@mailcue.io"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_valid"] is True


# ── 7. New Backend Validation Improvements Tests ──────────────────


def test_syntax_validation_reserved_domains() -> None:
    # Reject RFC 2606 and internal TLDs/domains
    assert validate_syntax("user@example.invalid").is_valid is False
    assert validate_syntax("user@myhost.internal").is_valid is False
    assert validate_syntax("user@domain.test").is_valid is False
    assert validate_syntax("user@example.com").is_valid is False
    assert validate_syntax("user@sub.example.net").is_valid is False
    assert validate_syntax("user@example.org").is_valid is False


@pytest.mark.asyncio
@patch("aiosmtplib.SMTP")
async def test_validate_mailbox_greylisting(mock_smtp_class: MagicMock) -> None:
    mock_smtp = AsyncMock()
    mock_smtp.is_connected = True
    mock_smtp.close = MagicMock()
    mock_smtp_class.return_value = mock_smtp

    # Setup connection, ehlo, mail response, and rcpt response (450 Greylisted)
    mock_smtp.mail.return_value = (250, "Sender OK")
    mock_smtp.rcpt.return_value = (
        450,
        "Requested mail action not taken: mailbox unavailable (greylisted)",
    )

    res = await validate_mailbox(
        domain="mailcue.io",
        mx_records=["10 mail.example.com."],
        target_email="test@mailcue.io",
        sender_email="sender@mailcue.local",
    )

    assert res.is_valid is None
    assert res.smtp_code == 450
    assert res.catch_all is False
    assert "Greylisted" in (res.error or "")


@pytest.mark.asyncio
@patch("aiosmtplib.SMTP")
async def test_validate_mailbox_greylisting_exception(mock_smtp_class: MagicMock) -> None:
    mock_smtp = AsyncMock()
    mock_smtp.is_connected = True
    mock_smtp.close = MagicMock()
    mock_smtp_class.return_value = mock_smtp

    # Setup connection to raise a 450 SMTPResponseException
    mock_smtp.connect.side_effect = aiosmtplib.SMTPResponseException(
        451, "Requested action aborted: local error in processing"
    )

    res = await validate_mailbox(
        domain="mailcue.io",
        mx_records=["10 mail.example.com."],
        target_email="test@mailcue.io",
        sender_email="sender@mailcue.local",
    )

    assert res.is_valid is None
    assert res.smtp_code == 451
    assert res.catch_all is False
    assert "Greylisted" in (res.error or "")


@pytest.mark.asyncio
@patch("app.emails.validation.settings")
async def test_validate_mailbox_smtp_disabled(mock_settings: MagicMock) -> None:
    mock_settings.validation_smtp_probe_enabled = False

    res = await validate_mailbox(
        domain="mailcue.io",
        mx_records=["10 mail.example.com."],
        target_email="test@mailcue.io",
        sender_email="sender@mailcue.local",
    )

    assert res.is_valid is None
    assert "SMTP probe disabled" in (res.error or "")


@pytest.mark.asyncio
async def test_validate_email_catch_all_mapping() -> None:
    mock_mx = [MagicMock(preference=10, exchange=dns.name.from_text("mail.example.com."))]
    mock_ns = [MagicMock(target=dns.name.from_text("ns1.example.com."))]
    mock_a = [MagicMock(address="192.0.2.1")]

    def mock_resolve(qname: str, rdtype: str) -> list[MagicMock]:
        if rdtype == "MX":
            return mock_mx
        if rdtype == "NS":
            return mock_ns
        if rdtype == "A":
            return mock_a
        raise dns.resolver.NoAnswer()

    mock_smtp = AsyncMock()
    mock_smtp.is_connected = True
    mock_smtp.close = MagicMock()
    mock_smtp.mail.return_value = (250, "Sender OK")
    mock_smtp.rcpt.side_effect = [
        (250, "Recipient OK"),  # Target email accepted
        (250, "Recipient OK"),  # Random email also accepted (catch-all!)
    ]

    from app.emails.validation import validate_email

    with (
        patch("app.emails.validation._resolver.resolve", side_effect=mock_resolve),
        patch("aiosmtplib.SMTP", return_value=mock_smtp),
    ):
        res = await validate_email("good@mailcue.io")
        assert res.is_valid is True
        assert res.status == "catch_all"
        assert res.mailbox.catch_all is True


@patch("app.emails.disposable.get_cache_file_path")
@patch("os.path.getmtime")
@patch("time.time")
@patch("asyncio.create_task")
def test_disposable_cache_age_checker(
    mock_create_task: MagicMock,
    mock_time: MagicMock,
    mock_getmtime: MagicMock,
    mock_get_cache_file_path: MagicMock,
    tmp_path: pytest.TempPathFactory,
) -> None:
    test_cache = tmp_path / "test_age.txt"
    test_cache.write_text("dummy")
    mock_get_cache_file_path.return_value = test_cache

    # 1. Age is 12 hours (43200 seconds) - shouldn't trigger update
    mock_time.return_value = 100000
    mock_getmtime.return_value = 100000 - 43200

    from app.emails.disposable import _check_cache_age_and_trigger_update

    _check_cache_age_and_trigger_update()
    mock_create_task.assert_not_called()

    # 2. Age is 25 hours (90000 seconds) - should trigger update
    mock_getmtime.return_value = 100000 - 90000
    _check_cache_age_and_trigger_update()
    mock_create_task.assert_called_once()
