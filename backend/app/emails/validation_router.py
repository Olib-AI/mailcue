"""Address validation, bounce ingestion, and staged-send endpoints.

These live on their own router so their literal paths are registered before
``GET /emails/{uid}``. A path parameter route matches any single segment, so a
route added after it in the same router is shadowed and never reached.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import scopes
from app.config import settings
from app.database import get_db
from app.dependencies import AuthContext, get_auth, require_scope
from app.emails.batch_validation import validate_batch
from app.emails.canary import apply_bounce, create_canary, decide
from app.emails.canary import count_for_user as count_canaries
from app.emails.canary import to_response as canary_to_response
from app.emails.dsn import parse_dsn
from app.emails.models import (
    DomainSendSuppression,
    EmailSendCanary,
    EmailSendCanaryRecipient,
)
from app.emails.schemas import (
    CreateSendCanaryRequest,
    DomainSuppressionEntry,
    DomainSuppressionListResponse,
    EmailBounceIngestRecipient,
    EmailBounceIngestRequest,
    EmailBounceIngestResponse,
    EmailValidationBatchRequest,
    EmailValidationBatchResponse,
    EmailValidationCalibrationBin,
    EmailValidationCalibrationResponse,
    SendCanaryListResponse,
    SendCanaryResponse,
)
from app.emails.validation import provider_id_for_domain, validate_syntax
from app.emails.validation_feedback import build_calibration_report, record_validation_feedback
from app.rate_limit import limiter

validation_router = APIRouter(prefix="/emails", tags=["Emails"])


@validation_router.post(
    "/validate-batch",
    response_model=EmailValidationBatchResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_VALIDATE))],
)
@limiter.limit(settings.validation_rate_limit)
async def validate_email_batch_endpoint(
    request: Request,
    body: EmailValidationBatchRequest = Body(...),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> EmailValidationBatchResponse:
    """Validate a list of addresses, using batch-level evidence and a bounce budget.

    Addresses at the same domain reveal that domain's naming convention and any
    generated name variants, neither of which is visible one address at a time.
    """
    if len(body.emails) > settings.validation_batch_max_addresses:
        raise HTTPException(
            status_code=422,
            detail=(
                f"A batch may contain at most {settings.validation_batch_max_addresses} addresses"
            ),
        )
    return await validate_batch(
        db,
        user_id=auth.user.id,
        emails=body.emails,
        target_bounce_rate=body.target_bounce_rate,
        include_domain_signals=body.include_domain_signals,
    )


@validation_router.get(
    "/validation-calibration",
    response_model=EmailValidationCalibrationResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_VALIDATE))],
)
async def get_validation_calibration(
    days: int = Query(90, ge=1, le=365),
    scope: str = Query("tenant", pattern="^(tenant|global)$"),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> EmailValidationCalibrationResponse:
    """Report how well issued risk scores matched the outcomes that followed.

    A score is only a probability once it has been checked against reality.
    """
    report = await build_calibration_report(
        db,
        user_id=None if scope == "global" else auth.user.id,
        days=days,
    )
    return EmailValidationCalibrationResponse(
        sample_size=report.sample_size,
        brier_score=report.brier_score,
        mean_predicted=report.mean_predicted,
        observed_rate=report.observed_rate,
        bins=[
            EmailValidationCalibrationBin(
                lower=item.lower,
                upper=item.upper,
                count=item.count,
                predicted_mean=item.predicted_mean,
                observed_rate=item.observed_rate,
            )
            for item in report.bins
        ],
    )


@validation_router.post(
    "/bounces/ingest",
    response_model=EmailBounceIngestResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_VALIDATE))],
)
@limiter.limit(settings.validation_rate_limit)
async def ingest_bounce(
    request: Request,
    body: EmailBounceIngestRequest = Body(...),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> EmailBounceIngestResponse:
    """Extract delivery outcomes from a raw notification and record them.

    Bounces the server already receives are the only labelled data that exists
    for an accept-all recipient, so they are ingested automatically rather than
    waiting for a caller to report each one by hand.
    """
    if not settings.validation_dsn_ingest_enabled:
        raise HTTPException(status_code=403, detail="Bounce ingestion is disabled")

    report = parse_dsn(body.raw_message)
    if not report.is_dsn:
        return EmailBounceIngestResponse(is_dsn=False, recorded=0)

    recorded: list[EmailBounceIngestRecipient] = []
    for entry in report.recipients:
        outcome = entry.outcome
        if outcome is None:
            continue
        syntax = validate_syntax(entry.recipient)
        if not syntax.is_valid or not syntax.domain:
            continue
        await record_validation_feedback(
            db,
            user_id=auth.user.id,
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
        recorded.append(
            EmailBounceIngestRecipient(
                recipient=entry.recipient,
                outcome=outcome,
                status=entry.status,
                smtp_code=entry.smtp_code,
                diagnostic_code=entry.diagnostic_code,
            )
        )

    return EmailBounceIngestResponse(is_dsn=True, recorded=len(recorded), recipients=recorded)


@validation_router.get(
    "/suppressed-domains",
    response_model=DomainSuppressionListResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_VALIDATE))],
)
async def list_suppressed_domains(
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DomainSuppressionListResponse:
    """List recipient domains paused after their measured bounce rate crossed the limit."""
    now = datetime.now(UTC)
    rows = (
        (
            await db.execute(
                select(DomainSendSuppression)
                .where(
                    or_(
                        DomainSendSuppression.expires_at.is_(None),
                        DomainSendSuppression.expires_at > now,
                    )
                )
                .order_by(DomainSendSuppression.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    entries = [
        DomainSuppressionEntry(
            domain=row.domain,
            reason=row.reason,
            hard_bounces=row.hard_bounces,
            observations=row.observations,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )
        for row in rows
    ]
    return DomainSuppressionListResponse(suppressions=entries, total=len(entries))


@validation_router.post(
    "/send-canaries",
    response_model=SendCanaryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope(scopes.EMAIL_SEND))],
)
async def create_send_canary(
    body: CreateSendCanaryRequest = Body(...),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> SendCanaryResponse:
    """Stage a send so a sample proves each domain before the rest is committed.

    There is no way to recall a message once it leaves the MTA, so the only
    control available is how much of the batch is committed at once.
    """
    if not settings.canary_enabled:
        raise HTTPException(status_code=403, detail="Staged sending is disabled")
    if len(body.recipients) > settings.validation_batch_max_addresses:
        raise HTTPException(
            status_code=422,
            detail=(
                f"A staged send may contain at most "
                f"{settings.validation_batch_max_addresses} recipients"
            ),
        )

    try:
        canary = await create_canary(db, user_id=auth.user.id, request=body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await canary_to_response(db, canary)


@validation_router.get(
    "/send-canaries",
    response_model=SendCanaryListResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_SEND))],
)
async def list_send_canaries(
    limit: int = Query(25, ge=1, le=100),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> SendCanaryListResponse:
    """List staged sends for the calling tenant, newest first."""
    rows = (
        (
            await db.execute(
                select(EmailSendCanary)
                .where(EmailSendCanary.user_id == auth.user.id)
                .order_by(EmailSendCanary.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return SendCanaryListResponse(
        canaries=[await canary_to_response(db, row) for row in rows],
        total=await count_canaries(db, auth.user.id),
    )


async def _load_canary(db: AsyncSession, canary_id: str, user_id: str) -> EmailSendCanary:
    canary = await db.scalar(
        select(EmailSendCanary).where(
            EmailSendCanary.id == canary_id, EmailSendCanary.user_id == user_id
        )
    )
    if canary is None:
        raise HTTPException(status_code=404, detail="Staged send not found")
    return canary


@validation_router.get(
    "/send-canaries/{canary_id}",
    response_model=SendCanaryResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_SEND))],
)
async def get_send_canary(
    canary_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> SendCanaryResponse:
    """Return the state of one staged send."""
    canary = await _load_canary(db, canary_id, auth.user.id)
    return await canary_to_response(db, canary)


@validation_router.post(
    "/send-canaries/{canary_id}/decide",
    response_model=SendCanaryResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_SEND))],
)
async def decide_send_canary(
    canary_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> SendCanaryResponse:
    """Resolve a staged send now instead of waiting for its hold window."""
    canary = await _load_canary(db, canary_id, auth.user.id)
    if canary.status != "probing":
        raise HTTPException(
            status_code=409,
            detail=f"Staged send is {canary.status}, not awaiting a decision",
        )
    await decide(db, canary)
    return await canary_to_response(db, canary)


@validation_router.post(
    "/send-canaries/{canary_id}/cancel",
    response_model=SendCanaryResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_SEND))],
)
async def cancel_send_canary(
    canary_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> SendCanaryResponse:
    """Cancel a staged send before its remaining recipients go out."""
    canary = await _load_canary(db, canary_id, auth.user.id)
    if canary.status in {"released", "blocked", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Staged send is already {canary.status}")
    await db.execute(
        update(EmailSendCanaryRecipient)
        .where(
            EmailSendCanaryRecipient.canary_id == canary.id,
            EmailSendCanaryRecipient.status == "pending",
        )
        .values(status="blocked", resolved_at=datetime.now(UTC))
    )
    canary.status = "cancelled"
    canary.decided_at = datetime.now(UTC)
    canary.decision_reason = "Cancelled by the caller."
    await db.commit()
    return await canary_to_response(db, canary)
