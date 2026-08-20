"""Staged sending that measures a domain before committing a batch to it.

SMTP has no recall. Gmail's undo is a client-side delay before the message is
handed to the MTA, and Exchange message recall only works inside one
organisation, so nothing can retrieve a message that has crossed to another
org. The exposure on an accept-all domain can only be bounded by not committing
the whole batch at once.

A small sample goes out first, the notification window is observed, and the
remainder is released only if the sample survived. The sample is chosen by
spreading across the batch's risk range rather than by taking the safest
addresses, because a sample that only contains safe addresses cannot
distinguish a domain that delivers everything from one that quietly discards
unknown recipients.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.emails.models import EmailSendCanary, EmailSendCanaryRecipient
from app.emails.schemas import (
    CreateSendCanaryRequest,
    SendCanaryRecipient,
    SendCanaryResponse,
    SendEmailRequest,
)
from app.emails.validation import validate_syntax
from app.emails.validation_feedback import domain_suppression

logger = logging.getLogger("mailcue.canary")


def _email_hash(email: str) -> str:
    return hmac.new(
        settings.secret_key.encode(), email.strip().lower().encode(), hashlib.sha256
    ).hexdigest()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def choose_sample(
    scored: list[tuple[str, float]], sample_size: int
) -> tuple[list[str], list[str]]:
    """Split recipients into a sample and the remainder held behind it.

    The sample spans the risk range: the riskiest address is always included so
    a domain that rejects unknown recipients reveals itself immediately, and the
    remaining slots are spread evenly across the rest so a uniform accept-all is
    also visible. A sample drawn only from the safe end would clear a batch that
    the risky end would have failed.
    """
    if not scored:
        return [], []
    ordered = sorted(scored, key=lambda item: item[1], reverse=True)
    size = max(1, min(sample_size, len(ordered)))
    if size >= len(ordered):
        return [email for email, _ in ordered], []

    picked_indices = {0}
    if size > 1:
        step = (len(ordered) - 1) / (size - 1)
        for position in range(1, size):
            picked_indices.add(min(round(position * step), len(ordered) - 1))
    # Rounding can collapse two slots onto one index; fill from the risky end.
    cursor = 0
    while len(picked_indices) < size and cursor < len(ordered):
        picked_indices.add(cursor)
        cursor += 1

    sample = [ordered[index][0] for index in sorted(picked_indices)]
    held = [email for index, (email, _) in enumerate(ordered) if index not in picked_indices]
    return sample, held


async def create_canary(
    db: AsyncSession,
    *,
    user_id: str,
    request: CreateSendCanaryRequest,
) -> EmailSendCanary:
    """Create a staged send with its recipients still unscored.

    Scoring probes every recipient over SMTP, which is far too slow to hold an
    HTTP request open for. The batch is persisted immediately and the scheduler
    scores it, picks the sample, and dispatches on its next tick.
    """
    sample_size = request.sample_size or settings.canary_default_sample_size
    hold_minutes = min(
        request.hold_minutes or settings.canary_default_hold_minutes,
        settings.canary_max_hold_minutes,
    )

    unique: dict[str, str] = {}
    for raw in request.recipients:
        candidate = (raw or "").strip()
        if not candidate:
            continue
        syntax = validate_syntax(candidate)
        if not syntax.is_valid or not syntax.domain:
            continue
        unique.setdefault(candidate.lower(), candidate)

    if not unique:
        raise ValueError("No valid recipient addresses were supplied")

    suppressed: set[str] = set()
    for address in unique.values():
        domain = address.rsplit("@", 1)[-1].lower()
        if domain in suppressed:
            continue
        if await domain_suppression(db, domain) is not None:
            suppressed.add(domain)

    sendable = [
        address
        for address in unique.values()
        if address.rsplit("@", 1)[-1].lower() not in suppressed
    ]
    skipped = [
        address for address in unique.values() if address.rsplit("@", 1)[-1].lower() in suppressed
    ]

    canary = EmailSendCanary(
        user_id=user_id,
        name=request.name or f"Staged send to {len(sendable)} recipients",
        status="pending" if sendable else "blocked",
        sample_size=sample_size,
        hold_minutes=hold_minutes,
        bounce_threshold=request.bounce_threshold,
        from_address=request.from_address,
        from_name=request.from_name,
        subject=request.subject,
        body=request.body,
        body_type=request.body_type,
        reply_to=request.reply_to,
        auto_release=request.auto_release,
        decision_reason=(
            None if sendable else "Every recipient domain is currently suppressed for sending."
        ),
    )
    db.add(canary)
    await db.flush()

    # Roles are assigned once scores exist, so every recipient starts held.
    for address in sendable:
        db.add(
            EmailSendCanaryRecipient(
                canary_id=canary.id,
                email=address,
                email_hash=_email_hash(address),
                domain=address.rsplit("@", 1)[-1].lower(),
                role="held",
                status="pending",
            )
        )
    for address in skipped:
        db.add(
            EmailSendCanaryRecipient(
                canary_id=canary.id,
                email=address,
                email_hash=_email_hash(address),
                domain=address.rsplit("@", 1)[-1].lower(),
                role="held",
                status="skipped",
            )
        )
    await db.commit()
    await db.refresh(canary)
    logger.info(
        "Staged send created: id=%s recipients=%d skipped=%d",
        canary.id,
        len(sendable),
        len(skipped),
    )
    return canary


async def score_and_assign_sample(db: AsyncSession, canary: EmailSendCanary) -> int:
    """Validate a staged send's recipients, then split them into sample and held.

    Runs in the scheduler rather than in the request that created the batch,
    because scoring probes every recipient over SMTP.
    """
    from app.emails.batch_validation import validate_batch

    rows = (
        (
            await db.execute(
                select(EmailSendCanaryRecipient).where(
                    EmailSendCanaryRecipient.canary_id == canary.id,
                    EmailSendCanaryRecipient.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    batch = await validate_batch(db, user_id=canary.user_id, emails=[row.email for row in rows])
    scores = {item.email.lower(): item.risk_score for item in batch.results}
    undeliverable = {item.email.lower() for item in batch.results if item.deliverable is False}

    now = datetime.now(UTC)
    scored: list[tuple[str, float]] = []
    for row in rows:
        row.risk_score = scores.get(row.email.lower(), 0.125)
        if row.email.lower() in undeliverable:
            # A confirmed dead address is never worth a send, sampled or not.
            row.status = "skipped"
            row.resolved_at = now
            continue
        scored.append((row.email, row.risk_score))

    sample, _held = choose_sample(scored, canary.sample_size)
    sample_set = {address.lower() for address in sample}
    for row in rows:
        if row.status == "pending" and row.email.lower() in sample_set:
            row.role = "sample"

    if not scored:
        canary.status = "blocked"
        canary.decided_at = now
        canary.decision_reason = "No recipient survived validation."
    await db.commit()
    logger.info(
        "Staged send scored: id=%s sendable=%d sample=%d",
        canary.id,
        len(scored),
        len(sample),
    )
    return len(scored)


def _send_request(canary: EmailSendCanary, recipients: list[str]) -> SendEmailRequest:
    return SendEmailRequest(
        from_address=canary.from_address,
        from_name=canary.from_name,
        to_addresses=recipients,
        subject=canary.subject,
        body=canary.body,
        body_type=canary.body_type,
        reply_to=canary.reply_to,
    )


async def dispatch_sample(db: AsyncSession, canary: EmailSendCanary) -> int:
    """Send the sample wave and open the observation window."""
    from app.emails.service import send_email

    rows = (
        (
            await db.execute(
                select(EmailSendCanaryRecipient).where(
                    EmailSendCanaryRecipient.canary_id == canary.id,
                    EmailSendCanaryRecipient.role == "sample",
                    EmailSendCanaryRecipient.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0

    now = datetime.now(UTC)
    sent = 0
    for row in rows:
        try:
            await send_email(_send_request(canary, [row.email]), db)
        except Exception as exc:
            logger.warning("Canary sample send failed: recipient=%s error=%s", row.email, exc)
            row.status = "skipped"
            row.resolved_at = now
            continue
        row.status = "sent"
        row.sent_at = now
        sent += 1

    canary.status = "probing"
    canary.sample_sent_at = now
    canary.decision_due_at = now + timedelta(minutes=canary.hold_minutes)
    await db.commit()
    logger.info("Staged send sample dispatched: id=%s sent=%d", canary.id, sent)
    return sent


async def release_remaining(db: AsyncSession, canary: EmailSendCanary, *, cutoff: float) -> int:
    """Send the held recipients whose risk sits below the observed failure point."""
    from app.emails.service import send_email

    rows = (
        (
            await db.execute(
                select(EmailSendCanaryRecipient).where(
                    EmailSendCanaryRecipient.canary_id == canary.id,
                    EmailSendCanaryRecipient.role == "held",
                    EmailSendCanaryRecipient.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )

    now = datetime.now(UTC)
    released = 0
    for row in rows:
        if row.risk_score is not None and row.risk_score >= cutoff:
            row.status = "blocked"
            row.resolved_at = now
            continue
        try:
            await send_email(_send_request(canary, [row.email]), db)
        except Exception as exc:
            logger.warning("Canary release send failed: recipient=%s error=%s", row.email, exc)
            row.status = "skipped"
            row.resolved_at = now
            continue
        row.status = "released"
        row.sent_at = now
        released += 1
    await db.commit()
    return released


async def decide(db: AsyncSession, canary: EmailSendCanary) -> str:
    """Apply the hold-window verdict to a staged send.

    Three outcomes are distinguished. A clean sample means the destination
    accepts and delivers, so everything is released. A wholly failed sample
    means the destination discards unknown recipients, so nothing more is sent.
    A partly failed sample means the destination does validate recipients and
    the per-address scores are meaningful, so only the addresses safer than the
    ones that failed are released.
    """
    rows = (
        (
            await db.execute(
                select(EmailSendCanaryRecipient).where(
                    EmailSendCanaryRecipient.canary_id == canary.id,
                    EmailSendCanaryRecipient.role == "sample",
                )
            )
        )
        .scalars()
        .all()
    )
    observed = [row for row in rows if row.status in {"sent", "delivered", "hard_bounce"}]
    if not observed:
        canary.status = "failed"
        canary.decided_at = datetime.now(UTC)
        canary.decision_reason = "No sample recipient could be sent."
        await db.commit()
        return canary.status

    bounced = [row for row in observed if row.status == "hard_bounce"]
    bounce_rate = len(bounced) / len(observed)
    now = datetime.now(UTC)

    if bounce_rate <= canary.bounce_threshold:
        released = await release_remaining(db, canary, cutoff=1.1)
        canary.status = "released"
        canary.decision_reason = (
            f"Sample of {len(observed)} produced no disqualifying bounce; released {released}."
        )
    elif len(bounced) == len(observed):
        await _block_remaining(db, canary)
        canary.status = "blocked"
        canary.decision_reason = (
            f"Every one of the {len(observed)} sampled recipients hard bounced."
        )
    else:
        safest_failure = min(
            (row.risk_score for row in bounced if row.risk_score is not None),
            default=1.0,
        )
        released = await release_remaining(db, canary, cutoff=safest_failure)
        canary.status = "released"
        canary.decision_reason = (
            f"{len(bounced)} of {len(observed)} sampled recipients bounced; released "
            f"{released} addresses scored below {safest_failure:.3f}."
        )

    canary.decided_at = now
    await db.commit()
    logger.info(
        "Staged send decided: id=%s status=%s reason=%s",
        canary.id,
        canary.status,
        canary.decision_reason,
    )
    return canary.status


async def _block_remaining(db: AsyncSession, canary: EmailSendCanary) -> None:
    rows = (
        (
            await db.execute(
                select(EmailSendCanaryRecipient).where(
                    EmailSendCanaryRecipient.canary_id == canary.id,
                    EmailSendCanaryRecipient.role == "held",
                    EmailSendCanaryRecipient.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    for row in rows:
        row.status = "blocked"
        row.resolved_at = now
    await db.commit()


async def apply_bounce(
    db: AsyncSession,
    *,
    email: str,
    outcome: str,
    smtp_code: int | None,
    enhanced_status: str | None,
) -> list[str]:
    """Attach an observed outcome to any staged send waiting on that recipient."""
    rows = (
        (
            await db.execute(
                select(EmailSendCanaryRecipient).where(
                    EmailSendCanaryRecipient.email_hash == _email_hash(email),
                    EmailSendCanaryRecipient.status == "sent",
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []

    now = datetime.now(UTC)
    touched: list[str] = []
    for row in rows:
        row.status = outcome if outcome in {"hard_bounce", "soft_bounce"} else "delivered"
        row.smtp_code = smtp_code
        row.enhanced_status = enhanced_status
        row.resolved_at = now
        touched.append(row.canary_id)
    await db.commit()
    return touched


async def to_response(db: AsyncSession, canary: EmailSendCanary) -> SendCanaryResponse:
    """Build the API representation of a staged send."""
    rows = (
        (
            await db.execute(
                select(EmailSendCanaryRecipient)
                .where(EmailSendCanaryRecipient.canary_id == canary.id)
                .order_by(EmailSendCanaryRecipient.role, EmailSendCanaryRecipient.email)
            )
        )
        .scalars()
        .all()
    )

    return SendCanaryResponse(
        id=canary.id,
        name=canary.name,
        status=canary.status,
        sample_size=canary.sample_size,
        hold_minutes=canary.hold_minutes,
        bounce_threshold=canary.bounce_threshold,
        auto_release=canary.auto_release,
        from_address=canary.from_address,
        subject=canary.subject,
        created_at=_aware(canary.created_at) or datetime.now(UTC),
        sample_sent_at=_aware(canary.sample_sent_at),
        decision_due_at=_aware(canary.decision_due_at),
        decided_at=_aware(canary.decided_at),
        decision_reason=canary.decision_reason,
        total_recipients=len(rows),
        sample_recipients=sum(1 for row in rows if row.role == "sample"),
        held_recipients=sum(1 for row in rows if row.role == "held"),
        hard_bounces=sum(1 for row in rows if row.status == "hard_bounce"),
        soft_bounces=sum(1 for row in rows if row.status == "soft_bounce"),
        recipients=[
            SendCanaryRecipient(
                email=row.email,
                role=row.role,
                status=row.status,
                risk_score=row.risk_score,
                smtp_code=row.smtp_code,
                enhanced_status=row.enhanced_status,
                sent_at=_aware(row.sent_at),
                resolved_at=_aware(row.resolved_at),
            )
            for row in rows
        ],
    )


async def count_for_user(db: AsyncSession, user_id: str) -> int:
    return int(
        await db.scalar(
            select(func.count(EmailSendCanary.id)).where(EmailSendCanary.user_id == user_id)
        )
        or 0
    )
