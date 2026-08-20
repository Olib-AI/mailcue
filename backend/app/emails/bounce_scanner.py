"""Automatic bounce ingestion from the mailboxes this server already owns.

An asynchronous bounce is the only ground truth that exists for a recipient a
probe could not classify, and MailCue receives those bounces itself. Waiting
for a caller to report each outcome by hand leaves the risk model permanently
cold, so notifications are read straight out of the mailboxes, parsed, and fed
back into the same store that scoring reads from.

Progress is tracked per mailbox by the highest UID already examined, which is
monotonic within an IMAP folder unless the folder is recreated. A recreated
folder resets UIDVALIDITY and restarts the scan, which at worst re-reads
notifications that have already been recorded.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.emails.canary import apply_bounce
from app.emails.dsn import parse_dsn
from app.emails.models import MailboxBounceScan
from app.emails.validation import provider_id_for_domain, validate_syntax
from app.emails.validation_feedback import record_validation_feedback
from app.mailboxes.models import Mailbox

logger = logging.getLogger("mailcue.bounce.scanner")

_TICK_SECONDS = 300.0
_MAX_MESSAGES_PER_MAILBOX = 100


async def _scan_mailbox(db: AsyncSession, mailbox: Mailbox) -> int:
    """Read new notifications in one mailbox and record the outcomes they carry."""
    from app.emails.service import get_email_raw, list_emails

    state = await db.scalar(
        select(MailboxBounceScan).where(MailboxBounceScan.mailbox == mailbox.address)
    )
    last_uid = state.last_uid if state is not None else 0

    try:
        listing = await list_emails(
            mailbox=mailbox.address,
            folder="INBOX",
            page=1,
            per_page=_MAX_MESSAGES_PER_MAILBOX,
            sort="date_desc",
        )
    except Exception as exc:
        logger.debug("Bounce scan could not list %s: %s", mailbox.address, exc)
        return 0

    candidates: list[str] = []
    highest = last_uid
    for summary in listing.emails:
        try:
            uid = int(summary.uid)
        except (TypeError, ValueError):
            continue
        highest = max(highest, uid)
        if uid <= last_uid:
            continue
        sender = (summary.from_address or "").lower()
        subject = (summary.subject or "").lower()
        # Cheap pre-filter so a busy mailbox does not fetch every message body.
        if (
            "mailer-daemon" in sender
            or "postmaster" in sender
            or "undeliverable" in subject
            or "delivery status notification" in subject
            or "returned mail" in subject
            or "delivery has failed" in subject
            or "failure notice" in subject
        ):
            candidates.append(str(uid))

    recorded = 0
    for candidate_uid in candidates:
        try:
            raw = await get_email_raw(mailbox.address, candidate_uid, "INBOX")
        except Exception as exc:
            logger.debug(
                "Bounce scan could not fetch %s/%s: %s", mailbox.address, candidate_uid, exc
            )
            continue
        report = parse_dsn(raw)
        if not report.is_dsn:
            continue
        for entry in report.recipients:
            outcome = entry.outcome
            if outcome is None:
                continue
            syntax = validate_syntax(entry.recipient)
            if not syntax.is_valid or not syntax.domain:
                continue
            if mailbox.user_id is None:
                continue
            await record_validation_feedback(
                db,
                user_id=mailbox.user_id,
                email=entry.recipient,
                domain=syntax.domain,
                outcome=outcome,
                smtp_code=entry.smtp_code,
                enhanced_status=entry.status,
                provider_id=await provider_id_for_domain(syntax.domain),
                source="dsn",
            )
            await apply_bounce(
                db,
                email=entry.recipient,
                outcome=outcome,
                smtp_code=entry.smtp_code,
                enhanced_status=entry.status,
            )
            recorded += 1

    if highest > last_uid:
        now = datetime.now(UTC)
        if state is None:
            db.add(MailboxBounceScan(mailbox=mailbox.address, last_uid=highest, scanned_at=now))
        else:
            state.last_uid = highest
            state.scanned_at = now
        await db.commit()

    if recorded:
        logger.info(
            "Bounce scan recorded outcomes: mailbox=%s outcomes=%d", mailbox.address, recorded
        )
    return recorded


async def scan_once() -> int:
    """Scan every active mailbox for new delivery status notifications."""
    async with AsyncSessionLocal() as db:
        mailboxes = (
            (
                await db.execute(
                    select(Mailbox).where(
                        Mailbox.is_active.is_(True), Mailbox.user_id.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        total = 0
        for mailbox in mailboxes:
            try:
                total += await _scan_mailbox(db, mailbox)
            except Exception:
                logger.exception("Bounce scan failed for mailbox %s", mailbox.address)
        return total


async def scanner_loop() -> None:
    """Periodically fold received bounces back into the risk model."""
    if not settings.validation_dsn_ingest_enabled:
        logger.info("Bounce ingestion disabled; scanner not started")
        return
    logger.info("Bounce scanner started (tick=%.0fs)", _TICK_SECONDS)
    while True:
        try:
            await scan_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Bounce scanner tick failed")
        await asyncio.sleep(_TICK_SECONDS)
