"""Feedback-backed risk calibration for SMTP accept-all recipients."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.emails.models import EmailValidationFeedback
from app.emails.schemas import EmailValidationCatchAllRisk

_HISTORY_DAYS = 180
_RECENT_DELIVERY_DAYS = 90
_MIN_DOMAIN_SAMPLES = 5
_PRIOR_RATE = 0.125
_PRIOR_STRENGTH = 20
_SEND_THRESHOLD = 0.04
_HOLD_THRESHOLD = 0.10


def _email_hash(email: str) -> str:
    return hmac.new(
        settings.secret_key.encode(), email.strip().lower().encode(), hashlib.sha256
    ).hexdigest()


async def record_validation_feedback(
    db: AsyncSession,
    *,
    user_id: str,
    email: str,
    domain: str,
    outcome: Literal["delivered", "hard_bounce", "soft_bounce"],
    smtp_code: int | None,
    enhanced_status: str | None,
) -> None:
    """Persist one tenant-isolated outcome without retaining the local part."""
    await db.execute(
        delete(EmailValidationFeedback).where(
            EmailValidationFeedback.user_id == user_id,
            EmailValidationFeedback.occurred_at
            < datetime.now(UTC) - timedelta(days=_HISTORY_DAYS),
        )
    )
    db.add(
        EmailValidationFeedback(
            user_id=user_id,
            email_hash=_email_hash(email),
            domain=domain.lower(),
            outcome=outcome,
            smtp_code=smtp_code,
            enhanced_status=enhanced_status,
        )
    )
    await db.commit()


def _risk(
    score: float,
    *,
    source: Literal["no_history", "exact_history", "domain_history"],
    sample_size: int,
    explanation: str,
    level_override: Literal["low", "medium", "high", "unknown"] | None = None,
    action_override: Literal["send", "caution", "hold"] | None = None,
) -> EmailValidationCatchAllRisk:
    if source == "no_history":
        level, action = "unknown", "caution"
    elif score <= _SEND_THRESHOLD:
        level, action = "low", "send"
    elif score >= _HOLD_THRESHOLD:
        level, action = "high", "hold"
    else:
        level, action = "medium", "caution"
    level = level_override or level
    action = action_override or action
    return EmailValidationCatchAllRisk(
        score=round(score, 4),
        level=level,
        recommended_action=action,
        source=source,
        sample_size=sample_size,
        explanation=explanation,
    )


async def assess_catch_all_risk(
    db: AsyncSession, *, user_id: str, email: str, domain: str
) -> EmailValidationCatchAllRisk:
    """Estimate hard-bounce risk using exact-recipient then domain history."""
    now = datetime.now(UTC)
    history_since = now - timedelta(days=_HISTORY_DAYS)
    latest = await db.scalar(
        select(EmailValidationFeedback)
        .where(
            EmailValidationFeedback.user_id == user_id,
            EmailValidationFeedback.email_hash == _email_hash(email),
            EmailValidationFeedback.occurred_at >= history_since,
        )
        .order_by(EmailValidationFeedback.occurred_at.desc())
        .limit(1)
    )
    if latest is not None and latest.outcome == "hard_bounce":
        return _risk(
            0.98,
            source="exact_history",
            sample_size=1,
            explanation="This exact recipient recently produced a hard bounce.",
        )
    latest_at = None
    if latest is not None:
        latest_at = latest.occurred_at
        if latest_at.tzinfo is None:
            latest_at = latest_at.replace(tzinfo=UTC)
    if (
        latest is not None
        and latest.outcome == "delivered"
        and latest_at is not None
        and latest_at >= now - timedelta(days=_RECENT_DELIVERY_DAYS)
    ):
        return _risk(
            0.02,
            source="exact_history",
            sample_size=1,
            explanation="This exact recipient has a recent reported delivery.",
        )
    if latest is not None and latest.outcome == "soft_bounce":
        return _risk(
            0.20,
            source="exact_history",
            sample_size=1,
            explanation="This exact recipient recently produced a temporary delivery failure.",
            level_override="medium",
            action_override="caution",
        )

    delivered_count, hard_count = (
        await db.execute(
            select(
                func.sum(case((EmailValidationFeedback.outcome == "delivered", 1), else_=0)),
                func.sum(case((EmailValidationFeedback.outcome == "hard_bounce", 1), else_=0)),
            ).where(
                EmailValidationFeedback.user_id == user_id,
                EmailValidationFeedback.domain == domain.lower(),
                EmailValidationFeedback.occurred_at >= history_since,
            )
        )
    ).one()
    delivered = int(delivered_count or 0)
    hard = int(hard_count or 0)
    sample_size = delivered + hard
    if sample_size >= _MIN_DOMAIN_SAMPLES:
        score = (hard + _PRIOR_RATE * _PRIOR_STRENGTH) / (sample_size + _PRIOR_STRENGTH)
        return _risk(
            score,
            source="domain_history",
            sample_size=sample_size,
            explanation="Estimated from tenant-specific outcomes for this accept-all domain.",
            # A few clean observations should improve confidence gradually,
            # not make the recommendation stricter than having no history.
            level_override="medium" if hard == 0 and score > _SEND_THRESHOLD else None,
            action_override="caution" if hard == 0 and score > _SEND_THRESHOLD else None,
        )
    return _risk(
        _PRIOR_RATE,
        source="no_history",
        sample_size=sample_size,
        explanation="Not enough tenant-specific delivery history; using the catch-all prior.",
    )
