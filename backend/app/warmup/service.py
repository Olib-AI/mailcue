"""Warmup account I/O and conservative campaign scheduler."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import email
import email.policy
import imaplib
import logging
import random
import re
import smtplib
import ssl
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from email.message import EmailMessage, Message
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosmtplib
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.domains.models import Domain
from app.mailboxes.models import Mailbox
from app.warmup.models import (
    WarmupAccount,
    WarmupCampaign,
    WarmupEvent,
    WarmupProviderState,
)
from app.warmup.schemas import WarmupAccountCreate, WarmupCampaignCreate

logger = logging.getLogger("mailcue.warmup")

_SUBJECTS = (
    "Quick check-in",
    "Following up",
    "A small update",
    "Checking the details",
    "One quick question",
    "Plans for this week",
    "Thanks for the update",
    "Confirming our notes",
)
_BODIES = (
    "Hi,\n\nJust checking in to make sure everything is on track. No rush—reply when convenient.\n\nBest,",
    "Hello,\n\nI wanted to follow up on our earlier note. Everything looks good from my side.\n\nThanks,",
    "Hi there,\n\nA quick confirmation that I received the update. Hope your week is going well.\n\nRegards,",
    "Hello,\n\nCould you confirm you received this when you have a moment?\n\nThank you,",
)
_REPLIES = (
    "Thanks, I received it. Everything looks good here.",
    "Confirmed—thank you for checking in.",
    "Got it. I appreciate the update.",
    "Yes, received. Have a great rest of your day.",
)

# Low-volume pacing floors. Campaign jitter can make these intervals longer,
# but never shorter for two outbound deliveries to the same receiving ISP.
_PROVIDER_MIN_GAP_MINUTES = {
    "gmail": 30,
    "yahoo": 45,
    "outlook": 45,
    "icloud": 45,
    "custom": 30,
}
_ENHANCED_STATUS_RE = re.compile(r"\b([245]\.\d{1,3}\.\d{1,3})\b")
_SMTP_CODE_RE = re.compile(r"\b([245]\d\d)\b")


def _fernet() -> Fernet:
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"mailcue-warmup-credentials",
        info=b"external-mailbox-password",
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(settings.secret_key.encode())))


def encrypt_password(password: str) -> str:
    return _fernet().encrypt(password.encode()).decode()


def decrypt_password(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def provider_defaults(provider: str) -> dict[str, object]:
    """Known endpoints; custom providers remain fully configurable."""
    return {
        "gmail": {
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
        },
        "yahoo": {
            "smtp_host": "smtp.mail.yahoo.com",
            "smtp_port": 587,
            "imap_host": "imap.mail.yahoo.com",
            "imap_port": 993,
        },
        "icloud": {
            "smtp_host": "smtp.mail.me.com",
            "smtp_port": 587,
            "imap_host": "imap.mail.me.com",
            "imap_port": 993,
        },
        "outlook": {
            "smtp_host": "smtp-mail.outlook.com",
            "smtp_port": 587,
            "imap_host": "outlook.office365.com",
            "imap_port": 993,
        },
    }.get(provider.lower(), {})


async def create_account(body: WarmupAccountCreate, db: AsyncSession) -> WarmupAccount:
    existing = (
        await db.execute(select(WarmupAccount).where(WarmupAccount.email == body.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError("A warmup account with this email already exists")
    account = WarmupAccount(
        id=str(uuid.uuid4()),
        name=body.name,
        email=body.email,
        provider=detect_provider(body.provider, body.smtp_host, body.imap_host),
        smtp_host=body.smtp_host,
        smtp_port=body.smtp_port,
        smtp_security=body.smtp_security,
        imap_host=body.imap_host,
        imap_port=body.imap_port,
        imap_security=body.imap_security,
        username=body.username,
        password_encrypted=encrypt_password(body.password),
        enabled=body.enabled,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


def _check_account_sync(account: WarmupAccount, password: str) -> None:
    context = ssl.create_default_context()
    if account.smtp_security == "ssl":
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(
            account.smtp_host, account.smtp_port, timeout=15, context=context
        )
    else:
        smtp = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=15)
    try:
        if account.smtp_security == "starttls":
            smtp.starttls(context=context)
        smtp.login(account.username, password)
    finally:
        with contextlib.suppress(Exception):
            smtp.quit()

    if account.imap_security == "ssl":
        imap: imaplib.IMAP4 = imaplib.IMAP4_SSL(
            account.imap_host, account.imap_port, ssl_context=context, timeout=15
        )
    else:
        imap = imaplib.IMAP4(account.imap_host, account.imap_port, timeout=15)
        if account.imap_security == "starttls":
            imap.starttls(ssl_context=context)
    try:
        imap.login(account.username, password)
        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            raise ConnectionError("IMAP login succeeded but INBOX could not be selected")
    finally:
        with contextlib.suppress(Exception):
            imap.logout()


async def check_account(account: WarmupAccount, db: AsyncSession) -> tuple[bool, str]:
    try:
        await asyncio.to_thread(
            _check_account_sync, account, decrypt_password(account.password_encrypted)
        )
        account.verified = True
        account.last_error = None
        message = "SMTP and IMAP authentication succeeded"
    except Exception as exc:
        account.verified = False
        account.last_error = str(exc)[:1000]
        message = account.last_error
    account.last_checked_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()
    return account.verified, message


async def create_campaign(body: WarmupCampaignCreate, db: AsyncSession) -> WarmupCampaign:
    accounts = await _validate_campaign_configuration(body, db)
    campaign = WarmupCampaign(id=str(uuid.uuid4()), **body.model_dump())
    db.add(campaign)
    await ensure_provider_states(campaign, accounts, db)
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def update_campaign(
    campaign: WarmupCampaign, body: WarmupCampaignCreate, db: AsyncSession
) -> WarmupCampaign:
    """Replace editable campaign settings without resetting progress or status."""
    accounts = await _validate_campaign_configuration(body, db)
    for key, value in body.model_dump().items():
        setattr(campaign, key, value)
    await ensure_provider_states(campaign, accounts, db)
    if campaign.status == "active" and campaign.next_run_at is None:
        campaign.next_run_at = datetime.now(UTC).replace(tzinfo=None)
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def _validate_campaign_configuration(
    body: WarmupCampaignCreate, db: AsyncSession
) -> list[WarmupAccount]:
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {body.timezone}") from exc
    if len(body.account_ids) != len(set(body.account_ids)):
        raise ValueError("External accounts cannot be selected more than once")
    accounts = (
        (await db.execute(select(WarmupAccount).where(WarmupAccount.id.in_(body.account_ids))))
        .scalars()
        .all()
    )
    if len(accounts) != len(set(body.account_ids)):
        raise ValueError("One or more external accounts do not exist")
    if any(not a.verified or not a.enabled for a in accounts):
        raise ValueError("All campaign accounts must be enabled and connection-tested")
    mailbox = (
        await db.execute(select(Mailbox).where(Mailbox.address == body.local_address))
    ).scalar_one_or_none()
    if mailbox is None:
        raise ValueError("The local sender must be an existing MailCue mailbox")
    await validate_sender_domain(body.local_address, db)
    return list(accounts)


def normalize_provider(provider: str) -> str:
    value = provider.strip().lower()
    aliases = {
        "google": "gmail",
        "google_workspace": "gmail",
        "microsoft": "outlook",
        "office365": "outlook",
        "hotmail": "outlook",
        "aol": "yahoo",
        "apple": "icloud",
    }
    return aliases.get(value, value or "custom")


def detect_provider(provider: str, smtp_host: str = "", imap_host: str = "") -> str:
    """Resolve hosted custom domains from their configured provider endpoints."""
    normalized = normalize_provider(provider)
    if normalized != "custom":
        return normalized
    hosts = f"{smtp_host} {imap_host}".lower()
    if "google" in hosts or "gmail" in hosts:
        return "gmail"
    if "yahoo" in hosts or "aol" in hosts:
        return "yahoo"
    if "outlook" in hosts or "office365" in hosts or "hotmail" in hosts:
        return "outlook"
    if "icloud" in hosts or "mail.me.com" in hosts:
        return "icloud"
    return "custom"


async def ensure_provider_states(
    campaign: WarmupCampaign, accounts: Sequence[WarmupAccount], db: AsyncSession
) -> list[WarmupProviderState]:
    existing = (
        (
            await db.execute(
                select(WarmupProviderState).where(WarmupProviderState.campaign_id == campaign.id)
            )
        )
        .scalars()
        .all()
    )
    by_provider = {state.provider: state for state in existing}
    for provider in {normalize_provider(account.provider) for account in accounts}:
        if provider not in by_provider:
            state = WarmupProviderState(
                id=str(uuid.uuid4()), campaign_id=campaign.id, provider=provider
            )
            db.add(state)
            by_provider[provider] = state
    await db.flush()
    return list(by_provider.values())


def extract_smtp_feedback(exc: Exception) -> tuple[int | None, str | None, str]:
    """Normalize stdlib/aiosmtplib exceptions and delayed DSN text."""
    raw_code = getattr(exc, "code", None)
    if raw_code is None:
        raw_code = getattr(exc, "smtp_code", None)
    code = int(raw_code) if isinstance(raw_code, int | str) and str(raw_code).isdigit() else None
    raw_message = getattr(exc, "message", None)
    if raw_message is None:
        raw_message = getattr(exc, "smtp_error", None)
    if isinstance(raw_message, bytes):
        response = raw_message.decode(errors="replace")
    else:
        response = str(raw_message or exc)
    if code is None and (match := _SMTP_CODE_RE.search(response)):
        code = int(match.group(1))
    enhanced_match = _ENHANCED_STATUS_RE.search(response)
    enhanced = enhanced_match.group(1) if enhanced_match else None
    return code, enhanced, response[:2000]


def apply_provider_feedback(
    state: WarmupProviderState,
    *,
    success: bool,
    now: datetime,
    smtp_code: int | None = None,
    enhanced_status: str | None = None,
    response: str | None = None,
) -> None:
    """Update provider health with conservative low-volume backoff."""
    if success:
        state.status = "healthy"
        state.sent_today = (state.sent_today or 0) + 1
        state.total_sent = (state.total_sent or 0) + 1
        state.consecutive_failures = 0
        state.last_sent_at = now
        state.last_smtp_code = None
        state.last_enhanced_status = None
        state.last_response = None
        state.paused_until = None
        gap = _PROVIDER_MIN_GAP_MINUTES.get(state.provider, 30)
        state.next_attempt_at = now + timedelta(minutes=gap)
        return

    state.failed_today = (state.failed_today or 0) + 1
    state.total_failed = (state.total_failed or 0) + 1
    state.consecutive_failures = (state.consecutive_failures or 0) + 1
    state.last_failure_at = now
    state.last_smtp_code = smtp_code
    state.last_enhanced_status = enhanced_status
    state.last_response = (response or "Unknown delivery failure")[:2000]
    is_permanent = (smtp_code is not None and 500 <= smtp_code < 600) or (
        enhanced_status is not None and enhanced_status.startswith("5.")
    )
    if is_permanent:
        # A controlled seed address should not hard-bounce. Hold this ISP until
        # an administrator fixes the account/policy and explicitly resumes it.
        state.status = "blocked"
        state.paused_until = None
        state.next_attempt_at = None
        return
    state.status = "cooling"
    base = 10 if state.provider == "gmail" else 15
    cooldown = min(360, max(base, 10 * (2 ** (state.consecutive_failures - 1))))
    state.paused_until = now + timedelta(minutes=cooldown)
    state.next_attempt_at = state.paused_until


def provider_is_available(state: WarmupProviderState, now: datetime) -> bool:
    if state.status == "blocked":
        return False
    available_at = state.paused_until or state.next_attempt_at
    if available_at is not None and available_at > now:
        return False
    if state.status == "cooling":
        state.status = "healthy"
        state.paused_until = None
    return True


async def validate_sender_domain(local_address: str, db: AsyncSession) -> None:
    """Refuse production warmup until core authentication is in place."""
    if not settings.is_production:
        return
    domain_name = local_address.rsplit("@", 1)[-1].lower()
    domain = (
        await db.execute(select(Domain).where(Domain.name == domain_name))
    ).scalar_one_or_none()
    if domain is None or not domain.is_active:
        raise ValueError("The sender domain is not active in MailCue")
    missing = [
        label
        for label, ready in (
            ("MX", domain.mx_verified),
            ("SPF", domain.spf_verified),
            ("DKIM", domain.dkim_verified),
            ("DMARC", domain.dmarc_verified),
        )
        if not ready
    ]
    if missing:
        raise ValueError("Verify the sender domain before warmup. Missing: " + ", ".join(missing))


async def set_campaign_status(
    campaign: WarmupCampaign, action: str, db: AsyncSession
) -> WarmupCampaign:
    now = datetime.now(UTC).replace(tzinfo=None)
    if action == "start":
        if not campaign.started_at:
            campaign.started_at = now
        campaign.status = "active"
        campaign.stopped_at = None
        campaign.next_run_at = now
    elif action == "pause":
        campaign.status = "paused"
        campaign.next_run_at = None
    elif action == "stop":
        campaign.status = "stopped"
        campaign.stopped_at = now
        campaign.next_run_at = None
    else:
        raise ValueError("Action must be start, pause, or stop")
    await db.commit()
    await db.refresh(campaign)
    return campaign


def _local_now(campaign: WarmupCampaign) -> datetime:
    return datetime.now(UTC).astimezone(ZoneInfo(campaign.timezone))


def _next_active_time(campaign: WarmupCampaign, now: datetime) -> datetime:
    local_now = now.replace(tzinfo=UTC).astimezone(ZoneInfo(campaign.timezone))
    start = time(campaign.active_hour_start)
    if campaign.active_hour_start <= local_now.hour < campaign.active_hour_end:
        return now
    day = local_now.date()
    if local_now.hour >= campaign.active_hour_end:
        day += timedelta(days=1)
    local_target = datetime.combine(day, start, tzinfo=local_now.tzinfo)
    local_target += timedelta(minutes=random.randint(0, 20))
    return local_target.astimezone(UTC).replace(tzinfo=None)


def _daily_target(campaign: WarmupCampaign, local_now: datetime) -> int:
    started = (campaign.started_at or datetime.now(UTC).replace(tzinfo=None)).replace(tzinfo=UTC)
    start_date = started.astimezone(local_now.tzinfo).date()
    day_number = max(0, (local_now.date() - start_date).days)
    return min(
        campaign.max_daily_volume, campaign.start_daily_volume + day_number * campaign.daily_ramp
    )


def _external_send_sync(account: WarmupAccount, msg: EmailMessage, password: str) -> None:
    context = ssl.create_default_context()
    if account.smtp_security == "ssl":
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(
            account.smtp_host, account.smtp_port, timeout=30, context=context
        )
    else:
        smtp = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=30)
    try:
        if account.smtp_security == "starttls":
            smtp.starttls(context=context)
        smtp.login(account.username, password)
        smtp.send_message(msg)
    finally:
        with contextlib.suppress(Exception):
            smtp.quit()


def _mark_external_seen_sync(account: WarmupAccount, sender: str, password: str) -> None:
    context = ssl.create_default_context()
    if account.imap_security == "ssl":
        imap: imaplib.IMAP4 = imaplib.IMAP4_SSL(
            account.imap_host, account.imap_port, ssl_context=context, timeout=15
        )
    else:
        imap = imaplib.IMAP4(account.imap_host, account.imap_port, timeout=15)
        if account.imap_security == "starttls":
            imap.starttls(ssl_context=context)
    try:
        imap.login(account.username, password)
        imap.select("INBOX")
        status, data = imap.search(None, "UNSEEN", "FROM", f'"{sender}"')
        if status == "OK" and data and data[0]:
            for message_id in data[0].split()[-20:]:
                imap.store(message_id, "+FLAGS", "\\Seen")
    finally:
        with contextlib.suppress(Exception):
            imap.logout()


def _mark_local_seen_sync(local_address: str, sender: str) -> None:
    context = ssl.create_default_context()
    if settings.imap_port == 993:
        imap: imaplib.IMAP4 = imaplib.IMAP4_SSL(
            settings.imap_host, settings.imap_port, ssl_context=context, timeout=15
        )
    else:
        imap = imaplib.IMAP4(settings.imap_host, settings.imap_port, timeout=15)
    try:
        imap.login(f"{local_address}*{settings.imap_master_user}", settings.imap_master_password)
        imap.select("INBOX")
        status, data = imap.search(None, "UNSEEN", "FROM", f'"{sender}"')
        if status == "OK" and data and data[0]:
            for message_id in data[0].split()[-20:]:
                imap.store(message_id, "+FLAGS", "\\Seen")
    finally:
        with contextlib.suppress(Exception):
            imap.logout()


def _dsn_feedback(message: Message) -> list[tuple[str, int | None, str | None, str]]:
    """Extract recipient/status tuples from an RFC 3464 delivery report."""
    results: list[tuple[str, int | None, str | None, str]] = []
    for part in message.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        payload = part.get_payload()
        blocks = payload if isinstance(payload, list) else []
        for block in blocks:
            if not isinstance(block, Message):
                continue
            action = str(block.get("Action", "")).lower()
            if action not in {"failed", "delayed"}:
                continue
            recipient_value = str(
                block.get("Final-Recipient") or block.get("Original-Recipient") or ""
            )
            recipient = recipient_value.split(";", 1)[-1].strip().lower()
            if "@" not in recipient:
                continue
            enhanced = str(block.get("Status") or "").strip() or None
            diagnostic = str(block.get("Diagnostic-Code") or "Delivery status notification")
            code_match = _SMTP_CODE_RE.search(diagnostic)
            code = int(code_match.group(1)) if code_match else None
            results.append((recipient, code, enhanced, diagnostic[:2000]))
    return results


def _fetch_local_dsns_sync(
    local_address: str, expected_recipients: set[str]
) -> list[tuple[str, int | None, str | None, str]]:
    """Read and consume unseen DSNs for configured warmup recipients."""
    context = ssl.create_default_context()
    if settings.imap_port == 993:
        imap: imaplib.IMAP4 = imaplib.IMAP4_SSL(
            settings.imap_host, settings.imap_port, ssl_context=context, timeout=15
        )
    else:
        imap = imaplib.IMAP4(settings.imap_host, settings.imap_port, timeout=15)
    feedback: list[tuple[str, int | None, str | None, str]] = []
    try:
        imap.login(f"{local_address}*{settings.imap_master_user}", settings.imap_master_password)
        if imap.select("INBOX")[0] != "OK":
            return feedback
        status, data = imap.uid("search", None, "UNSEEN")  # type: ignore[arg-type]
        if status != "OK" or not data or not data[0]:
            return feedback
        for uid in data[0].split()[-100:]:
            fetch_status, fetched = imap.uid("fetch", uid, "(RFC822)")
            if fetch_status != "OK":
                continue
            raw = next(
                (
                    item[1]
                    for item in fetched
                    if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes)
                ),
                None,
            )
            if raw is None:
                continue
            message = email.message_from_bytes(raw, policy=email.policy.default)
            parsed = [row for row in _dsn_feedback(message) if row[0] in expected_recipients]
            if parsed:
                feedback.extend(parsed)
                imap.uid("store", uid, "+FLAGS", "\\Seen")
    finally:
        with contextlib.suppress(Exception):
            imap.logout()
    return feedback


async def ingest_delivery_feedback(
    campaign: WarmupCampaign,
    accounts: Sequence[WarmupAccount],
    states: list[WarmupProviderState],
    db: AsyncSession,
) -> int:
    """Apply asynchronous Postfix DSNs before choosing the next provider."""
    by_email = {account.email.lower(): account for account in accounts}
    by_provider = {state.provider: state for state in states}
    try:
        feedback = await asyncio.to_thread(
            _fetch_local_dsns_sync, campaign.local_address, set(by_email)
        )
    except Exception:
        logger.warning("Could not poll warmup delivery feedback", exc_info=True)
        return 0
    now = datetime.now(UTC).replace(tzinfo=None)
    for recipient, code, enhanced, response in feedback:
        account = by_email[recipient]
        provider = normalize_provider(account.provider)
        state = by_provider[provider]
        apply_provider_feedback(
            state,
            success=False,
            now=now,
            smtp_code=code,
            enhanced_status=enhanced,
            response=response,
        )
        db.add(
            WarmupEvent(
                id=str(uuid.uuid4()),
                campaign_id=campaign.id,
                account_id=account.id,
                provider=provider,
                direction="delivery_feedback",
                status="bounced" if (code or 0) >= 500 else "deferred",
                subject="Delivery status notification",
                smtp_code=code,
                enhanced_status=enhanced,
                error=response,
            )
        )
    if feedback:
        campaign.total_failed += len(feedback)
        await db.flush()
    return len(feedback)


async def _record_engagement(
    campaign: WarmupCampaign, account: WarmupAccount, direction: str
) -> None:
    """Mark prior messages as read on the side about to answer."""
    try:
        if direction == "external_to_local":
            await asyncio.to_thread(
                _mark_external_seen_sync,
                account,
                campaign.local_address,
                decrypt_password(account.password_encrypted),
            )
        else:
            await asyncio.to_thread(_mark_local_seen_sync, campaign.local_address, account.email)
    except Exception:
        # Engagement is useful, but a transient IMAP error must not duplicate or
        # suppress the scheduled SMTP delivery.
        logger.warning("Could not mark prior warmup messages as read", exc_info=True)


async def _send_one(
    campaign: WarmupCampaign,
    account: WarmupAccount,
    direction: str,
    reply_to: WarmupEvent | None,
) -> tuple[str, str]:
    subject = (
        f"Re: {reply_to.subject.removeprefix('Re: ')}"
        if reply_to is not None
        else random.choice(_SUBJECTS)
    )
    msg = EmailMessage()
    msg["From"] = campaign.local_address if direction == "local_to_external" else account.email
    msg["To"] = account.email if direction == "local_to_external" else campaign.local_address
    msg["Subject"] = subject
    msg["Message-ID"] = email.utils.make_msgid(domain=msg["From"].split("@", 1)[1])
    msg["Date"] = email.utils.formatdate(localtime=True)
    if reply_to is not None and reply_to.message_id:
        msg["In-Reply-To"] = reply_to.message_id
        msg["References"] = reply_to.message_id
    msg.set_content(random.choice(_REPLIES if reply_to is not None else _BODIES))
    await _record_engagement(campaign, account, direction)
    if direction == "local_to_external":
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            start_tls=False,
            use_tls=False,
        )
    else:
        await asyncio.to_thread(
            _external_send_sync, account, msg, decrypt_password(account.password_encrypted)
        )
    return subject, str(msg["Message-ID"])


async def process_campaign(campaign_id: str) -> None:
    async with AsyncSessionLocal() as db:
        now = datetime.now(UTC).replace(tzinfo=None)
        # Atomic claim: only one API worker may handle a due slot. A short
        # lease makes the slot recoverable if that worker exits mid-delivery.
        claim = await db.execute(
            update(WarmupCampaign)
            .where(
                WarmupCampaign.id == campaign_id,
                WarmupCampaign.status == "active",
                WarmupCampaign.next_run_at.is_not(None),
                WarmupCampaign.next_run_at <= now,
            )
            .values(next_run_at=now + timedelta(minutes=5))
        )
        if claim.rowcount != 1:  # type: ignore[attr-defined]
            await db.rollback()
            return
        await db.commit()
        campaign = await db.get(WarmupCampaign, campaign_id)
        if campaign is None:
            return
        accounts = (
            (
                await db.execute(
                    select(WarmupAccount).where(
                        WarmupAccount.id.in_(campaign.account_ids),
                        WarmupAccount.enabled.is_(True),
                        WarmupAccount.verified.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not accounts:
            campaign.status = "paused"
            campaign.next_run_at = None
            await db.commit()
            logger.warning("Paused warmup campaign %s: no healthy accounts", campaign.id)
            return

        states = await ensure_provider_states(campaign, accounts, db)
        active_providers = {normalize_provider(account.provider) for account in accounts}
        active_states = [state for state in states if state.provider in active_providers]
        local_now = _local_now(campaign)
        today = local_now.date().isoformat()
        if campaign.volume_date != today:
            campaign.volume_date = today
            campaign.messages_sent_today = 0
        for state in states:
            if state.volume_date != today:
                state.volume_date = today
                state.sent_today = 0
                state.failed_today = 0
        await ingest_delivery_feedback(campaign, accounts, states, db)

        active_time = _next_active_time(campaign, now)
        target = _daily_target(campaign, local_now)
        if active_time > now:
            campaign.next_run_at = active_time
            await db.commit()
            return

        last_by_account: dict[str, WarmupEvent | None] = {}
        for candidate in accounts:
            last_by_account[candidate.id] = (
                await db.execute(
                    select(WarmupEvent)
                    .where(
                        WarmupEvent.campaign_id == campaign.id,
                        WarmupEvent.account_id == candidate.id,
                        WarmupEvent.status == "sent",
                    )
                    .order_by(desc(WarmupEvent.created_at))
                    .limit(1)
                )
            ).scalar_one_or_none()

        # Complete pending conversations first. These inbound replies do not
        # consume MailCue's outbound ISP reputation budget.
        reply_accounts = [
            account
            for account in accounts
            if last_by_account[account.id] is not None
            and last_by_account[account.id].direction == "local_to_external"  # type: ignore[union-attr]
        ]
        if reply_accounts:
            account = random.choice(reply_accounts)
            direction = "external_to_local"
        else:
            if campaign.messages_sent_today >= target:
                tomorrow = local_now.date() + timedelta(days=1)
                local_target = datetime.combine(
                    tomorrow, time(campaign.active_hour_start), tzinfo=local_now.tzinfo
                )
                campaign.next_run_at = local_target.astimezone(UTC).replace(
                    tzinfo=None
                ) + timedelta(minutes=random.randint(0, 20))
                await db.commit()
                return

            provider_count = max(1, len(active_states))
            provider_target = (target + provider_count - 1) // provider_count
            eligible_states = [
                state
                for state in active_states
                if provider_is_available(state, now) and state.sent_today < provider_target
            ]
            if not eligible_states:
                future = [
                    value
                    for state in active_states
                    for value in (state.paused_until, state.next_attempt_at)
                    if value is not None and value > now
                ]
                campaign.next_run_at = min(future) if future else now + timedelta(hours=6)
                await db.commit()
                return
            lowest_load = min((state.sent_today, state.total_sent) for state in eligible_states)
            chosen_state = random.choice(
                [
                    state
                    for state in eligible_states
                    if (state.sent_today, state.total_sent) == lowest_load
                ]
            )
            outbound_accounts = [
                candidate
                for candidate in accounts
                if normalize_provider(candidate.provider) == chosen_state.provider
                and (
                    last_by_account[candidate.id] is None
                    or last_by_account[candidate.id].direction != "local_to_external"  # type: ignore[union-attr]
                )
            ]
            if not outbound_accounts:
                chosen_state.next_attempt_at = now + timedelta(minutes=15)
                campaign.next_run_at = chosen_state.next_attempt_at
                await db.commit()
                return
            account = random.choice(outbound_accounts)
            direction = "local_to_external"

        last = last_by_account[account.id]
        reply_to = (
            last if last is not None and random.randint(1, 100) <= campaign.reply_rate else None
        )
        campaign.next_run_at = now + timedelta(
            minutes=random.randint(campaign.min_delay_minutes, campaign.max_delay_minutes)
        )
        await db.commit()  # claim the next slot before network I/O

        event = WarmupEvent(
            id=str(uuid.uuid4()),
            campaign_id=campaign.id,
            account_id=account.id,
            provider=normalize_provider(account.provider),
            direction=direction,
            status="failed",
            subject="Warmup message",
        )
        try:
            event.subject, event.message_id = await _send_one(
                campaign, account, direction, reply_to
            )
            event.status = "sent"
            campaign.total_sent += 1
            if direction == "local_to_external":
                campaign.messages_sent_today += 1
                provider_state = next(
                    state
                    for state in states
                    if state.provider == normalize_provider(account.provider)
                )
                apply_provider_feedback(provider_state, success=True, now=now)
        except Exception as exc:
            code, enhanced, response = extract_smtp_feedback(exc)
            event.error = response
            event.smtp_code = code
            event.enhanced_status = enhanced
            campaign.total_failed += 1
            account.last_error = event.error
            if direction == "local_to_external":
                provider_state = next(
                    state
                    for state in states
                    if state.provider == normalize_provider(account.provider)
                )
                apply_provider_feedback(
                    provider_state,
                    success=False,
                    now=now,
                    smtp_code=code,
                    enhanced_status=enhanced,
                    response=response,
                )
            logger.exception("Warmup delivery failed for campaign %s", campaign.id)
        db.add(event)
        await db.commit()


async def scheduler_loop() -> None:
    """Run due campaigns; safe to cancel during application shutdown."""
    while True:
        try:
            async with AsyncSessionLocal() as db:
                now = datetime.now(UTC).replace(tzinfo=None)
                due = (
                    (
                        await db.execute(
                            select(WarmupCampaign.id)
                            .where(
                                WarmupCampaign.status == "active",
                                WarmupCampaign.next_run_at.is_not(None),
                                WarmupCampaign.next_run_at <= now,
                            )
                            .limit(20)
                        )
                    )
                    .scalars()
                    .all()
                )
            for campaign_id in due:
                await process_campaign(campaign_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Warmup scheduler iteration failed")
        await asyncio.sleep(15)
