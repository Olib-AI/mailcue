"""Admin API tests for controlled email warmup configuration."""

from __future__ import annotations

import email
import email.policy
import smtplib
from datetime import datetime, timedelta

from httpx import AsyncClient

from app.warmup.models import WarmupProviderState
from app.warmup.service import (
    _BODIES,
    _REPLIES,
    _SUBJECTS,
    _dsn_feedback,
    apply_provider_feedback,
    detect_provider,
    extract_smtp_feedback,
)


def test_warmup_content_pools_are_varied_and_unique() -> None:
    for pool in (_SUBJECTS, _BODIES, _REPLIES):
        assert len(pool) >= 24
        assert len(pool) == len(set(pool))


async def test_account_credentials_are_write_only(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/warmup/accounts",
        json={
            "name": "Owned Gmail",
            "email": "owned@gmail.com",
            "provider": "gmail",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_security": "starttls",
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "imap_security": "ssl",
            "username": "owned@gmail.com",
            "password": "app-password",
            "ownership_confirmed": True,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "owned@gmail.com"
    assert "password" not in body
    assert "password_encrypted" not in body
    assert body["verified"] is False


async def test_account_requires_ownership_confirmation(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/warmup/accounts",
        json={
            "name": "Not confirmed",
            "email": "external@example.com",
            "smtp_host": "smtp.example.com",
            "imap_host": "imap.example.com",
            "username": "external@example.com",
            "password": "secret",
            "ownership_confirmed": False,
        },
    )
    assert response.status_code == 422


async def test_campaign_lifecycle(client: AsyncClient, _engine_and_session) -> None:
    _engine, factory = _engine_and_session
    account_response = await client.post(
        "/api/v1/warmup/accounts",
        json={
            "name": "External",
            "email": "external@example.net",
            "smtp_host": "smtp.example.net",
            "imap_host": "imap.example.net",
            "username": "external@example.net",
            "password": "app-password",
            "ownership_confirmed": True,
        },
    )
    account_id = account_response.json()["id"]

    from app.mailboxes.models import Mailbox
    from app.warmup.models import WarmupAccount

    async with factory() as db:
        account = await db.get(WarmupAccount, account_id)
        assert account is not None
        account.verified = True
        db.add(
            Mailbox(
                address="sender@mailcue.local",
                display_name="Sender",
                domain="mailcue.local",
                user_id="test-user-id",
            )
        )
        await db.commit()

    second_account_response = await client.post(
        "/api/v1/warmup/accounts",
        json={
            "name": "Gmail seed",
            "email": "seed@gmail.com",
            "provider": "gmail",
            "smtp_host": "smtp.gmail.com",
            "imap_host": "imap.gmail.com",
            "username": "seed@gmail.com",
            "password": "app-password",
            "ownership_confirmed": True,
        },
    )
    second_account_id = second_account_response.json()["id"]
    async with factory() as db:
        second_account = await db.get(WarmupAccount, second_account_id)
        assert second_account is not None
        second_account.verified = True
        await db.commit()

    response = await client.post(
        "/api/v1/warmup/campaigns",
        json={
            "name": "New domain",
            "local_address": "sender@mailcue.local",
            "account_ids": [account_id],
            "start_daily_volume": 5,
            "daily_ramp": 2,
            "max_daily_volume": 25,
            "min_delay_minutes": 10,
            "max_delay_minutes": 45,
            "reply_rate": 70,
            "active_hour_start": 8,
            "active_hour_end": 20,
            "timezone": "UTC",
        },
    )
    assert response.status_code == 201, response.text
    campaign_id = response.json()["id"]
    assert response.json()["status"] == "draft"

    provider_states = await client.get(f"/api/v1/warmup/provider-states?campaign_id={campaign_id}")
    assert provider_states.status_code == 200
    assert len(provider_states.json()) == 1
    assert provider_states.json()[0]["provider"] == "custom"
    assert provider_states.json()[0]["status"] == "healthy"

    started = await client.post(f"/api/v1/warmup/campaigns/{campaign_id}/start", json={})
    assert started.status_code == 200
    assert started.json()["status"] == "active"
    assert started.json()["next_run_at"] is not None

    updated = await client.put(
        f"/api/v1/warmup/campaigns/{campaign_id}",
        json={
            "name": "Updated domain warmup",
            "local_address": "sender@mailcue.local",
            "account_ids": [account_id, second_account_id],
            "start_daily_volume": 4,
            "daily_ramp": 1,
            "max_daily_volume": 30,
            "min_delay_minutes": 15,
            "max_delay_minutes": 60,
            "reply_rate": 80,
            "active_hour_start": 7,
            "active_hour_end": 21,
            "timezone": "UTC",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Updated domain warmup"
    assert updated.json()["account_ids"] == [account_id, second_account_id]
    assert updated.json()["status"] == "active"
    assert updated.json()["next_run_at"] == started.json()["next_run_at"]
    assert updated.json()["total_sent"] == 0

    provider_states = await client.get(f"/api/v1/warmup/provider-states?campaign_id={campaign_id}")
    assert {state["provider"] for state in provider_states.json()} == {"custom", "gmail"}

    paused = await client.post(f"/api/v1/warmup/campaigns/{campaign_id}/pause", json={})
    assert paused.json()["status"] == "paused"
    assert paused.json()["next_run_at"] is None

    stopped = await client.post(f"/api/v1/warmup/campaigns/{campaign_id}/stop", json={})
    assert stopped.json()["status"] == "stopped"
    assert stopped.json()["stopped_at"] is not None


def test_provider_feedback_cools_down_then_blocks() -> None:
    state = WarmupProviderState(id="state-1", campaign_id="campaign-1", provider="gmail")
    now = datetime(2026, 7, 25, 12, 0, 0)

    apply_provider_feedback(
        state,
        success=False,
        now=now,
        smtp_code=421,
        enhanced_status="4.7.28",
        response="421 4.7.28 rate limited",
    )
    assert state.status == "cooling"
    assert state.paused_until == now + timedelta(minutes=10)

    apply_provider_feedback(
        state,
        success=False,
        now=now,
        smtp_code=421,
        enhanced_status="4.7.28",
        response="421 4.7.28 rate limited",
    )
    assert state.paused_until == now + timedelta(minutes=20)

    apply_provider_feedback(state, success=True, now=now + timedelta(minutes=20))
    assert state.status == "healthy"
    assert state.consecutive_failures == 0
    assert state.next_attempt_at == now + timedelta(minutes=50)

    apply_provider_feedback(
        state,
        success=False,
        now=now + timedelta(minutes=50),
        smtp_code=550,
        enhanced_status="5.7.1",
        response="550 5.7.1 rejected",
    )
    assert state.status == "blocked"
    assert state.next_attempt_at is None


def test_smtp_exception_and_dsn_are_normalized() -> None:
    exc = smtplib.SMTPResponseException(421, b"4.7.28 unusual sending rate")
    code, enhanced, response = extract_smtp_feedback(exc)
    assert code == 421
    assert enhanced == "4.7.28"
    assert "unusual sending rate" in response

    raw = b"""MIME-Version: 1.0
Content-Type: multipart/report; report-type=delivery-status; boundary=dsn
Subject: Delivery Status Notification (Delay)

--dsn
Content-Type: text/plain

Delivery delayed.
--dsn
Content-Type: message/delivery-status

Reporting-MTA: dns; mail.example.test

Final-Recipient: rfc822; seed@gmail.com
Action: delayed
Status: 4.7.28
Diagnostic-Code: smtp; 421 4.7.28 Unusual sending rate detected

--dsn--
"""
    message = email.message_from_bytes(raw, policy=email.policy.default)
    feedback = _dsn_feedback(message)
    assert feedback == [
        (
            "seed@gmail.com",
            421,
            "4.7.28",
            "smtp; 421 4.7.28 Unusual sending rate detected",
        )
    ]


def test_custom_domain_provider_is_detected_from_hosts() -> None:
    assert detect_provider("custom", "smtp.gmail.com", "imap.gmail.com") == "gmail"
    assert detect_provider("custom", "smtp.office365.com", "outlook.office365.com") == "outlook"
    assert detect_provider("custom", "smtp.example.net", "imap.example.net") == "custom"
