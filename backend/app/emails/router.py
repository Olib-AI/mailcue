"""Email CRUD router -- list, get, raw, attachments, send, inject, delete."""

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import scopes
from app.auth.models import User
from app.config import settings
from app.database import get_db
from app.deliverability.service import delete_message_reports
from app.dependencies import AuthContext, get_auth, require_admin, require_scope
from app.emails.batch_validation import risk_schema, validate_batch
from app.emails.canary import (
    count_for_user as count_canaries,
)
from app.emails.canary import (
    create_canary,
    decide,
)
from app.emails.canary import (
    to_response as canary_to_response,
)
from app.emails.dsn import parse_dsn
from app.emails.models import DomainSendSuppression, EmailSendCanary
from app.emails.mx_providers import UNKNOWN_PROVIDER, classify_mx, parse_mx_hosts
from app.emails.schemas import (
    BulkInjectRequest,
    BulkInjectResponse,
    CreateSendCanaryRequest,
    DomainSuppressionEntry,
    DomainSuppressionListResponse,
    EmailBounceIngestRecipient,
    EmailBounceIngestRequest,
    EmailBounceIngestResponse,
    EmailDetail,
    EmailListResponse,
    EmailValidationBatchRequest,
    EmailValidationBatchResponse,
    EmailValidationCalibrationBin,
    EmailValidationCalibrationResponse,
    EmailValidationFeedbackRequest,
    EmailValidationFeedbackResponse,
    EmailValidationRequest,
    EmailValidationResponse,
    InjectEmailRequest,
    SendCanaryListResponse,
    SendCanaryResponse,
    SendEmailRequest,
)
from app.emails.service import (
    bulk_inject,
    delete_email,
    get_attachment,
    get_email,
    get_email_raw,
    inject_email,
    list_emails,
    send_email,
)
from app.emails.validation import validate_email_detailed, validate_syntax
from app.emails.validation_feedback import (
    assess_catch_all_risk,
    build_calibration_report,
    record_prediction,
    record_validation_feedback,
)
from app.mailboxes.router import verify_mailbox_access
from app.mailboxes.service import get_mailbox_by_address
from app.rate_limit import limiter


def _require_non_production() -> None:
    """Block test-only endpoints when running in production mode.

    Inject is a test-data fixture: it bypasses SMTP/DKIM/SPF and APPENDs
    straight into IMAP.  Allowing it in production would let an admin
    create messages that *appear* delivered without ever passing through
    the normal authentication path — a real foot-gun on a public server.
    """
    if settings.is_production:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


router = APIRouter(prefix="/emails", tags=["Emails"])


@router.get(
    "",
    response_model=EmailListResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def list_all_emails(
    mailbox: str = Query(..., description="Target mailbox address (user@domain)"),
    folder: str = Query("INBOX", description="IMAP folder name"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    search: str | None = Query(None, description="Full-text search query"),
    sort: str = Query("date_desc", description="Sort order (date_asc, date_desc)"),
    thread_view: bool = Query(
        False,
        description="Group conversations: sort the page by (thread_id, date asc).",
    ),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> EmailListResponse:
    """List emails in a mailbox with pagination, search, and sorting.

    Emails are fetched directly from IMAP. The ``search`` parameter
    maps to IMAP ``TEXT`` search which covers subject and body.
    """
    await verify_mailbox_access(mailbox, auth, db)
    return await list_emails(
        mailbox=mailbox,
        folder=folder,
        page=page,
        per_page=page_size,
        search=search,
        sort=sort,
        thread_view=thread_view,
    )


@router.get(
    "/{uid}",
    response_model=EmailDetail,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def get_single_email(
    uid: str,
    mailbox: str = Query(..., description="Target mailbox address"),
    folder: str = Query("INBOX"),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> EmailDetail:
    """Fetch a single email by its IMAP UID with full body and headers."""
    await verify_mailbox_access(mailbox, auth, db)
    return await get_email(
        mailbox=mailbox, uid=uid, folder=folder, db=db, gpg_user_id=auth.user.id
    )


@router.get(
    "/{uid}/raw",
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def get_raw_email(
    uid: str,
    mailbox: str = Query(..., description="Target mailbox address"),
    folder: str = Query("INBOX"),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download the raw RFC 5322 source of an email as a ``.eml`` file."""
    await verify_mailbox_access(mailbox, auth, db)
    raw = await get_email_raw(mailbox=mailbox, uid=uid, folder=folder)
    return Response(
        content=raw,
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{uid}.eml"'},
    )


@router.get(
    "/{uid}/attachments/{part_id}",
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def download_attachment(
    uid: str,
    part_id: str,
    mailbox: str = Query(..., description="Target mailbox address"),
    folder: str = Query("INBOX"),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download a specific MIME attachment identified by its part ID."""
    await verify_mailbox_access(mailbox, auth, db)
    data, content_type, filename = await get_attachment(
        mailbox=mailbox, uid=uid, part_id=part_id, folder=folder
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/send",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_scope(scopes.EMAIL_SEND))],
)
async def send_new_email(
    body: SendEmailRequest,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Send an email via the local SMTP server (Postfix).

    The sender address (``from_address``) must belong to the
    authenticated user's mailbox (admins may send from any).
    """
    await verify_mailbox_access(body.from_address, auth, db)
    try:
        message_id = await send_email(
            body,
            db=db,
            sign=body.sign,
            encrypt=body.encrypt,
            gpg_user_id=auth.user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"message": "Email accepted for delivery", "message_id": message_id}


@router.post(
    "/inject",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_require_non_production)],
)
async def inject_single_email(
    body: InjectEmailRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Inject an email directly into a mailbox via IMAP APPEND.

    **Admin only.** Bypasses SMTP delivery entirely -- the email
    appears in the target mailbox immediately. Ideal for test data setup.
    """
    uid = await inject_email(
        body, db=db, sign=body.sign, encrypt=body.encrypt, gpg_user_id=_admin.id
    )
    return {"uid": uid, "mailbox": body.mailbox}


@router.post(
    "/bulk-inject",
    response_model=BulkInjectResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_require_non_production)],
)
async def bulk_inject_emails(
    body: BulkInjectRequest,
    _admin: User = Depends(require_admin),
) -> BulkInjectResponse:
    """Inject multiple emails into mailboxes in a single request.

    **Admin only.** Each email in the ``emails`` array is injected
    independently. Partial failures are reported in the response
    without aborting the entire batch.
    """
    return await bulk_inject(body)


@router.delete(
    "/{uid}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_scope(scopes.EMAIL_DELETE))],
)
async def delete_single_email(
    uid: str,
    mailbox: str = Query(..., description="Target mailbox address"),
    folder: str = Query("INBOX"),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an email by UID (sets \\Deleted flag and expunges)."""
    await verify_mailbox_access(mailbox, auth, db)
    mailbox_record = await get_mailbox_by_address(mailbox, db)
    await delete_email(mailbox=mailbox, uid=uid, folder=folder)
    await delete_message_reports(
        db,
        user_id=auth.user.id,
        mailbox_id=mailbox_record.id,
        folder=folder,
        uids=[uid],
    )


@router.post(
    "/validate",
    response_model=EmailValidationResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_VALIDATE))],
)
@limiter.limit(settings.validation_rate_limit)
async def validate_email_endpoint(
    request: Request,
    body: EmailValidationRequest = Body(...),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> EmailValidationResponse:
    """Validate email address format, DNS domain MX/NS, SMTP availability, and disposable status."""
    outcome = await validate_email_detailed(body.email)
    result = outcome.response
    provider = outcome.profile.provider if outcome.profile else UNKNOWN_PROVIDER

    if result.status == "catch_all" and result.syntax.domain:
        assessment = await assess_catch_all_risk(
            db,
            user_id=auth.user.id,
            email=result.email,
            domain=result.syntax.domain,
            provider=provider,
            local_part_delta=outcome.local_part_delta,
            local_part_notes=outcome.local_part_notes,
            domain_signal_delta=outcome.domain_signal_delta,
            domain_signal_notes=outcome.domain_signal_notes,
            probe=outcome.probe,
        )
        result = result.model_copy(update={"catch_all_risk": risk_schema(assessment)})
        score = assessment.score
    elif result.deliverable is False:
        score = 1.0
    elif result.status == "valid":
        score = 0.005
    else:
        score = 0.25

    if result.syntax.domain:
        # Retaining the score lets a later bounce or delivery be joined back to
        # what was claimed at the time, which is the only way the published
        # probability can be checked rather than asserted.
        await record_prediction(
            db,
            user_id=auth.user.id,
            email=result.email,
            domain=result.syntax.domain,
            provider_id=provider.id,
            status=result.status,
            score=score,
        )
    return result


@router.post(
    "/validation-feedback",
    response_model=EmailValidationFeedbackResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_VALIDATE))],
)
@limiter.limit(settings.validation_rate_limit)
async def create_email_validation_feedback(
    request: Request,
    body: EmailValidationFeedbackRequest = Body(...),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> EmailValidationFeedbackResponse:
    """Record an organic delivery result used to calibrate catch-all risk."""
    syntax = validate_syntax(body.email)
    if not syntax.is_valid or not syntax.domain:
        raise HTTPException(status_code=422, detail="A valid public email address is required")
    await record_validation_feedback(
        db,
        user_id=auth.user.id,
        email=body.email,
        domain=syntax.domain,
        outcome=body.outcome,
        smtp_code=body.smtp_code,
        enhanced_status=body.enhanced_status,
        provider_id=await _provider_for_domain(syntax.domain),
    )
    return EmailValidationFeedbackResponse(recorded=True, outcome=body.outcome)


async def _provider_for_domain(domain: str) -> str | None:
    """Classify a domain's receiving provider so outcomes pool at that level."""
    from app.emails.validation import validate_dns

    try:
        dns_result = await validate_dns(domain)
    except Exception:
        return None
    if not dns_result.mx_records:
        return None
    return classify_mx(parse_mx_hosts(dns_result.mx_records), domain).provider.id


@router.post(
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


@router.get(
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


@router.post(
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
            provider_id=await _provider_for_domain(syntax.domain),
            source="dsn",
        )
        from app.emails.canary import apply_bounce

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


@router.get(
    "/suppressed-domains",
    response_model=DomainSuppressionListResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_VALIDATE))],
)
async def list_suppressed_domains(
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DomainSuppressionListResponse:
    """List recipient domains paused after their measured bounce rate crossed the limit."""
    from datetime import UTC, datetime

    from sqlalchemy import or_, select

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


@router.post(
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


@router.get(
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
    from sqlalchemy import select

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
    from sqlalchemy import select

    canary = await db.scalar(
        select(EmailSendCanary).where(
            EmailSendCanary.id == canary_id, EmailSendCanary.user_id == user_id
        )
    )
    if canary is None:
        raise HTTPException(status_code=404, detail="Staged send not found")
    return canary


@router.get(
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


@router.post(
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


@router.post(
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
    from datetime import UTC, datetime

    from sqlalchemy import update

    from app.emails.models import EmailSendCanaryRecipient

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
