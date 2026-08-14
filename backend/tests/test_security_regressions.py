"""Regression tests for production security boundaries."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError as PydanticValidationError

from app.auth.models import User
from app.auth.utils import create_access_token
from app.config import Settings, settings
from app.deliverability.links import _public_addresses
from app.dependencies import _user_from_jwt
from app.emails.validation import _resolve_public_smtp_addresses
from app.events.bus import EventBus
from app.forwarding.models import ForwardingRule
from app.forwarding.service import _matches_pattern, _validate_webhook_destination
from app.gpg.models import GpgKey
from app.gpg.service import get_key_for_address
from app.mailboxes.models import Mailbox
from app.mailboxes.schemas import MailboxCreateRequest
from app.mailboxes.service import _safe_maildir_path


@pytest.mark.parametrize(
    "username",
    ["../root", "a/b", "a\\b", "a:b", "a\nadmin", ".hidden", "two..dots"],
)
def test_mailbox_username_rejects_config_and_path_injection(username: str) -> None:
    with pytest.raises(PydanticValidationError):
        MailboxCreateRequest(
            username=username,
            domain="example.com",
            password="correct horse battery staple",
        )


def test_maildir_builder_cannot_escape_storage_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "mail_storage_path", str(tmp_path))
    assert _safe_maildir_path("example.com", "alice").is_relative_to(tmp_path)
    with pytest.raises(ValueError):
        _safe_maildir_path("..", "etc")


def test_public_smtp_strips_sender_supplied_verdict_headers() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    master = (repository_root / "rootfs/etc/postfix/master.cf").read_text()
    checks = (repository_root / "rootfs/etc/postfix/inbound_header_checks").read_text()
    opendkim = (repository_root / "rootfs/etc/opendkim/opendkim.conf").read_text()
    opendmarc = (repository_root / "rootfs/etc/opendmarc/opendmarc.conf").read_text()
    policyd_spf = (
        repository_root / "rootfs/etc/postfix-policyd-spf-python/policyd-spf.conf"
    ).read_text()

    public_smtp = master.split("# ---- Port 587", maxsplit=1)[0]
    assert "header_checks=regexp:/etc/postfix/inbound_header_checks" in public_smtp
    assert "/^Authentication-Results:/" in checks
    assert "/^Received-SPF:/" in checks
    assert "/^X-Spam-[^:]*:/" in checks
    assert "AuthservID        mailcue" in opendkim
    assert "AlwaysAddARHeader yes" in opendkim
    assert "AuthservID              mailcue" in opendmarc
    assert "Header_Type = AR" in policyd_spf
    assert "Authserv_Id = mailcue" in policyd_spf


async def test_event_bus_only_delivers_events_for_allowed_mailboxes() -> None:
    bus = EventBus()
    _, alice = await bus.subscribe(allowed_mailboxes={"alice@example.com"})
    _, bob = await bus.subscribe(allowed_mailboxes={"bob@example.com"})

    await bus.publish("email.received", {"mailbox": "alice@example.com", "subject": "secret"})

    assert (await alice.get())["data"]["subject"] == "secret"
    assert bob.empty()


async def test_forwarding_rules_are_scoped_to_mailbox_owner(
    _engine_and_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.forwarding.service import process_incoming_email

    _engine, factory = _engine_and_session
    alice_id = "security-alice"
    bob_id = "security-bob"
    async with factory() as db:
        db.add_all(
            [
                User(
                    id=alice_id,
                    username="security-alice",
                    email="alice@example.com",
                    hashed_password="unused",
                ),
                User(
                    id=bob_id,
                    username="security-bob",
                    email="bob@example.com",
                    hashed_password="unused",
                ),
                Mailbox(address="alice@example.com", domain="example.com", user_id=alice_id),
                Mailbox(address="bob@example.com", domain="example.com", user_id=bob_id),
                ForwardingRule(
                    user_id=alice_id,
                    name="alice rule",
                    action_type="webhook",
                    action_config='{"url":"https://alice.example.net/hook"}',
                ),
                ForwardingRule(
                    user_id=bob_id,
                    name="bob theft rule",
                    action_type="webhook",
                    action_config='{"url":"https://bob.example.net/hook"}',
                ),
            ]
        )
        await db.commit()

        fired: list[str] = []

        async def fake_execute(rule: ForwardingRule, _data: dict[str, Any]) -> None:
            fired.append(rule.user_id)

        async def fake_get_email(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("metadata-only test")

        monkeypatch.setattr("app.forwarding.service.execute_rule_action", fake_execute)
        monkeypatch.setattr("app.emails.service.get_email", fake_get_email)
        count = await process_incoming_email(
            db,
            from_address="sender@outside.net",
            to_address="alice@example.com",
            subject="private",
            mailbox="alice@example.com",
            uid="1",
        )

    assert count == 1
    assert fired == [alice_id]


async def test_webhook_ssrf_blocks_private_destinations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()

    async def private_lookup(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [(2, 1, 6, "", ("127.0.0.1", 80))]

    monkeypatch.setattr(loop, "getaddrinfo", private_lookup)
    with pytest.raises(Exception, match="public IP"):
        await _validate_webhook_destination("http://internal.example/hook")


async def test_smtp_probe_discards_private_destinations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()

    async def private_lookup(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [(2, 1, 6, "", ("169.254.169.254", 25))]

    monkeypatch.setattr(loop, "getaddrinfo", private_lookup)
    assert await _resolve_public_smtp_addresses("mx.example") == []


async def test_deliverability_provider_resolution_rejects_mixed_public_and_private_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()

    async def mixed_lookup(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr(loop, "getaddrinfo", mixed_lookup)
    assert await _public_addresses("provider.example", 443) == []


def test_forwarding_regex_timeout_fails_closed() -> None:
    assert not _matches_pattern(r"(a+)+$", "a" * 100_000 + "!")


async def test_revoked_token_version_is_rejected(_engine_and_session: Any) -> None:
    _engine, factory = _engine_and_session
    user = User(
        id="revoked-user",
        username="revoked-user",
        email="revoked@example.com",
        hashed_password="unused",
        token_version=1,
    )
    async with factory() as db:
        db.add(user)
        await db.commit()
        old_token = create_access_token(user.id, token_version=0)
        with pytest.raises(HTTPException) as exc_info:
            await _user_from_jwt(old_token, db)
    assert exc_info.value.status_code == 401


async def test_gpg_lookup_is_tenant_scoped(_engine_and_session: Any) -> None:
    _engine, factory = _engine_and_session
    async with factory() as db:
        db.add_all(
            [
                User(id="gpg-a", username="gpg-a", email="gpg-a@example.com", hashed_password="x"),
                User(id="gpg-b", username="gpg-b", email="gpg-b@example.com", hashed_password="x"),
                GpgKey(
                    user_id="gpg-a",
                    mailbox_address="recipient@outside.net",
                    fingerprint="A" * 40,
                    key_id="A" * 16,
                ),
                GpgKey(
                    user_id="gpg-b",
                    mailbox_address="recipient@outside.net",
                    fingerprint="B" * 40,
                    key_id="B" * 16,
                ),
            ]
        )
        await db.commit()
        alice_key = await get_key_for_address("recipient@outside.net", db, user_id="gpg-a")
        bob_key = await get_key_for_address("recipient@outside.net", db, user_id="gpg-b")
    assert alice_key is not None and alice_key.fingerprint == "A" * 40
    assert bob_key is not None and bob_key.fingerprint == "B" * 40


def test_production_configuration_rejects_known_credentials() -> None:
    unsafe = Settings(
        _env_file=None,
        mode="production",
        domain="example.com",
        hostname="mail.example.com",
        admin_password="mailcue",
        secret_key="x" * 32,
        imap_master_password="master-secret",
        tls_cert_path="/cert.pem",
        tls_key_path="/key.pem",
    )
    with pytest.raises(ValueError, match="Unsafe production configuration"):
        unsafe.validate_production_security()
