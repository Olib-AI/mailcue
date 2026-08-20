"""Database layer feeding the accept-all risk model.

Outcome history is stored per tenant but read at three levels: the exact
recipient, the recipient domain, and the receiving provider. The domain level
is shared across tenants once enough distinct tenants have contributed that no
single tenant's traffic is identifiable, because whether a domain bounces is a
property of that domain and scoping it per tenant leaves every new customer
starting from nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.emails.models import (
    DomainSendSuppression,
    EmailValidationFeedback,
    EmailValidationPrediction,
)
from app.emails.mx_providers import UNKNOWN_PROVIDER, MxProvider
from app.emails.risk_model import (
    CalibrationReport,
    ObservationCounts,
    ProbeEvidence,
    RiskAssessment,
    calibration_report,
    compute_risk,
    exact_recipient_risk,
)

logger = logging.getLogger("mailcue.validation.feedback")

Outcome = Literal["delivered", "hard_bounce", "soft_bounce"]

_HISTORY_DAYS = 180
_RECENT_DELIVERY_DAYS = 90
_PREDICTION_MATCH_DAYS = 30
_PREDICTION_RETENTION_DAYS = 365
_SUPPRESSION_MIN_OBSERVATIONS = 8
_SUPPRESSION_HARD_RATE = 0.30
_SUPPRESSION_DAYS = 30


def _email_hash(email: str) -> str:
    return hmac.new(
        settings.secret_key.encode(), email.strip().lower().encode(), hashlib.sha256
    ).hexdigest()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def record_prediction(
    db: AsyncSession,
    *,
    user_id: str,
    email: str,
    domain: str,
    provider_id: str | None,
    status: str,
    score: float,
) -> None:
    """Store the score issued for an address so calibration can be measured later."""
    await db.execute(
        delete(EmailValidationPrediction).where(
            EmailValidationPrediction.user_id == user_id,
            EmailValidationPrediction.created_at
            < datetime.now(UTC) - timedelta(days=_PREDICTION_RETENTION_DAYS),
        )
    )
    db.add(
        EmailValidationPrediction(
            user_id=user_id,
            email_hash=_email_hash(email),
            domain=domain.lower(),
            provider_id=provider_id,
            status=status,
            score=score,
        )
    )
    await db.commit()


async def record_validation_feedback(
    db: AsyncSession,
    *,
    user_id: str,
    email: str,
    domain: str,
    outcome: Outcome,
    smtp_code: int | None,
    enhanced_status: str | None,
    provider_id: str | None = None,
    source: str = "api",
) -> None:
    """Persist one delivery outcome and link it to any prediction made for it."""
    now = datetime.now(UTC)
    email_hash = _email_hash(email)
    normalized_domain = domain.lower()

    await db.execute(
        delete(EmailValidationFeedback).where(
            EmailValidationFeedback.user_id == user_id,
            EmailValidationFeedback.occurred_at < now - timedelta(days=_HISTORY_DAYS),
        )
    )

    predicted_score = await db.scalar(
        select(EmailValidationPrediction.score)
        .where(
            EmailValidationPrediction.email_hash == email_hash,
            EmailValidationPrediction.created_at >= now - timedelta(days=_PREDICTION_MATCH_DAYS),
        )
        .order_by(EmailValidationPrediction.created_at.desc())
        .limit(1)
    )

    db.add(
        EmailValidationFeedback(
            user_id=user_id,
            email_hash=email_hash,
            domain=normalized_domain,
            outcome=outcome,
            smtp_code=smtp_code,
            enhanced_status=enhanced_status,
            provider_id=provider_id,
            source=source,
            predicted_score=predicted_score,
        )
    )
    await db.commit()

    if outcome == "hard_bounce":
        await _maybe_suppress_domain(db, normalized_domain)


async def _counts_for(
    db: AsyncSession,
    *,
    domain: str | None = None,
    provider_id: str | None = None,
    user_id: str | None = None,
    since: datetime,
) -> ObservationCounts:
    filters = [EmailValidationFeedback.occurred_at >= since]
    if domain is not None:
        filters.append(EmailValidationFeedback.domain == domain)
    if provider_id is not None:
        filters.append(EmailValidationFeedback.provider_id == provider_id)
    if user_id is not None:
        filters.append(EmailValidationFeedback.user_id == user_id)

    row = (
        await db.execute(
            select(
                func.sum(case((EmailValidationFeedback.outcome == "delivered", 1), else_=0)),
                func.sum(case((EmailValidationFeedback.outcome == "hard_bounce", 1), else_=0)),
                func.sum(case((EmailValidationFeedback.outcome == "soft_bounce", 1), else_=0)),
                func.count(func.distinct(EmailValidationFeedback.user_id)),
            ).where(*filters)
        )
    ).one()
    return ObservationCounts(
        delivered=int(row[0] or 0),
        hard_bounce=int(row[1] or 0),
        soft_bounce=int(row[2] or 0),
        tenants=int(row[3] or 0),
    )


async def _domain_counts(
    db: AsyncSession, *, user_id: str, domain: str, since: datetime
) -> tuple[ObservationCounts, bool]:
    """Return domain observations, preferring the shared aggregate when it is safe.

    The shared aggregate is only used once enough distinct tenants and enough
    total outcomes have accumulated that it cannot be attributed to one tenant.
    """
    own = await _counts_for(db, domain=domain, user_id=user_id, since=since)
    if not settings.validation_cross_tenant_risk_enabled:
        return own, False

    shared = await _counts_for(db, domain=domain, since=since)
    if (
        shared.tenants >= settings.validation_cross_tenant_min_tenants
        and shared.decisive >= settings.validation_cross_tenant_min_samples
    ):
        return shared, True
    return own, False


async def assess_catch_all_risk(
    db: AsyncSession,
    *,
    user_id: str,
    email: str,
    domain: str,
    provider: MxProvider | None = None,
    local_part_delta: float = 0.0,
    local_part_notes: list[str] | None = None,
    domain_signal_delta: float = 0.0,
    domain_signal_notes: list[str] | None = None,
    probe: ProbeEvidence | None = None,
) -> RiskAssessment:
    """Estimate hard-bounce risk for an accept-all recipient."""
    provider = provider or UNKNOWN_PROVIDER
    now = datetime.now(UTC)
    since = now - timedelta(days=_HISTORY_DAYS)
    normalized_domain = domain.lower()

    latest = await db.scalar(
        select(EmailValidationFeedback)
        .where(
            EmailValidationFeedback.user_id == user_id,
            EmailValidationFeedback.email_hash == _email_hash(email),
            EmailValidationFeedback.occurred_at >= since,
        )
        .order_by(EmailValidationFeedback.occurred_at.desc())
        .limit(1)
    )
    if latest is not None:
        occurred_at = _aware(latest.occurred_at)
        recent_delivery = occurred_at is not None and occurred_at >= now - timedelta(
            days=_RECENT_DELIVERY_DAYS
        )
        exact = exact_recipient_risk(
            cast("Outcome", latest.outcome), recent_delivery=recent_delivery
        )
        if exact is not None:
            exact.provider_id = provider.id
            return exact

    domain_counts, shared = await _domain_counts(
        db, user_id=user_id, domain=normalized_domain, since=since
    )
    provider_counts = ObservationCounts()
    if provider.id not in {"unknown", "no_mx"}:
        provider_counts = await _counts_for(db, provider_id=provider.id, since=since)

    return compute_risk(
        provider=provider,
        provider_counts=provider_counts,
        domain_counts=domain_counts,
        domain_counts_shared=shared,
        local_part_delta=local_part_delta,
        local_part_notes=local_part_notes,
        domain_signal_delta=domain_signal_delta,
        domain_signal_notes=domain_signal_notes,
        probe=probe,
    )


async def _maybe_suppress_domain(db: AsyncSession, domain: str) -> None:
    """Pause a domain whose measured hard-bounce rate crossed the circuit-breaker limit."""
    since = datetime.now(UTC) - timedelta(days=_HISTORY_DAYS)
    counts = await _counts_for(db, domain=domain, since=since)
    if counts.decisive < _SUPPRESSION_MIN_OBSERVATIONS:
        return
    rate = counts.hard_bounce / counts.decisive
    if rate < _SUPPRESSION_HARD_RATE:
        return

    now = datetime.now(UTC)
    existing = await db.scalar(
        select(DomainSendSuppression).where(DomainSendSuppression.domain == domain)
    )
    reason = (
        f"{counts.hard_bounce} of {counts.decisive} recorded outcomes at this domain were "
        f"hard bounces."
    )
    if existing is None:
        db.add(
            DomainSendSuppression(
                domain=domain,
                reason=reason[:255],
                hard_bounces=counts.hard_bounce,
                observations=counts.decisive,
                expires_at=now + timedelta(days=_SUPPRESSION_DAYS),
            )
        )
    else:
        existing.reason = reason[:255]
        existing.hard_bounces = counts.hard_bounce
        existing.observations = counts.decisive
        existing.expires_at = now + timedelta(days=_SUPPRESSION_DAYS)
    await db.commit()
    logger.warning("Domain suppressed for sending: domain=%s rate=%.3f", domain, rate)


async def domain_suppression(db: AsyncSession, domain: str) -> DomainSendSuppression | None:
    """Return an active suppression for a domain, if one exists."""
    record = await db.scalar(
        select(DomainSendSuppression).where(DomainSendSuppression.domain == domain.lower())
    )
    if record is None:
        return None
    expires_at = _aware(record.expires_at)
    if expires_at is not None and expires_at < datetime.now(UTC):
        return None
    return record


async def build_calibration_report(
    db: AsyncSession,
    *,
    user_id: str | None = None,
    days: int = 90,
) -> CalibrationReport:
    """Measure how well issued scores matched the outcomes that followed."""
    since = datetime.now(UTC) - timedelta(days=days)
    filters = [
        EmailValidationFeedback.occurred_at >= since,
        EmailValidationFeedback.predicted_score.is_not(None),
        EmailValidationFeedback.outcome != "soft_bounce",
    ]
    if user_id is not None:
        filters.append(EmailValidationFeedback.user_id == user_id)

    rows = (
        await db.execute(
            select(
                EmailValidationFeedback.predicted_score,
                EmailValidationFeedback.outcome,
            ).where(*filters)
        )
    ).all()
    observations = [
        (float(score), outcome == "hard_bounce") for score, outcome in rows if score is not None
    ]
    return calibration_report(observations)
