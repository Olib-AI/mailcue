"""Deliverability history, baseline, and comparison API."""

from __future__ import annotations

import csv
import html
import json
from io import StringIO

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import scopes
from app.database import get_db
from app.deliverability.schemas import (
    BaselineUpdateRequest,
    DeliverabilityAlertList,
    DeliverabilityAlertResponse,
    DeliverabilityCapabilities,
    DeliverabilityComparison,
    DeliverabilityPolicyEvaluationResponse,
    DeliverabilityPolicyResponse,
    DeliverabilityPolicyWrite,
    DeliverabilityProviderResponse,
    DeliverabilityProviderWrite,
    DeliverabilityReportList,
    DeliverabilityRunResponse,
    DeliverabilityScheduleResponse,
    DeliverabilityScheduleWrite,
    DeliverabilityTrend,
)
from app.deliverability.service import (
    acknowledge_alert,
    compare_reports,
    delete_policy,
    delete_provider,
    delete_schedule,
    evaluate_policy,
    get_alert,
    get_artifact,
    get_capabilities,
    get_policy,
    get_provider,
    get_report,
    get_report_record,
    get_run,
    get_schedule,
    get_trend,
    list_alerts,
    list_policies,
    list_providers,
    list_reports,
    list_runs_for_report,
    list_schedules,
    resolve_comparison_base,
    save_policy,
    save_provider,
    save_schedule,
    set_baseline,
)
from app.dependencies import AuthContext, get_auth, require_scope
from app.emails.schemas import DeliverabilityReport
from app.exceptions import AuthorizationError
from app.mailboxes.models import Mailbox
from app.mailboxes.router import verify_mailbox_access
from app.mailboxes.service import get_mailbox_by_address

router = APIRouter(prefix="/deliverability", tags=["Deliverability"])


def _verify_record_key_access(record_mailbox: str, auth: AuthContext) -> None:
    if not auth.mailbox_allowed(record_mailbox):
        raise AuthorizationError("This API key is not permitted to access this mailbox")


@router.get(
    "/capabilities",
    response_model=DeliverabilityCapabilities,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def capabilities(
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityCapabilities:
    return await get_capabilities(db, user_id=auth.user.id)


@router.get(
    "/providers",
    response_model=list[DeliverabilityProviderResponse],
    dependencies=[Depends(require_scope(scopes.MAILBOX_READ))],
)
async def providers(
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> list[DeliverabilityProviderResponse]:
    return await list_providers(db, user_id=auth.user.id)


@router.post(
    "/providers",
    response_model=DeliverabilityProviderResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope(scopes.MAILBOX_MANAGE))],
)
async def create_provider(
    body: DeliverabilityProviderWrite,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityProviderResponse:
    if body.kind == "placement" and not auth.user.is_admin:
        raise AuthorizationError("Seed inbox providers require an administrator")
    return await save_provider(db, user_id=auth.user.id, body=body)


@router.put(
    "/providers/{provider_id}",
    response_model=DeliverabilityProviderResponse,
    dependencies=[Depends(require_scope(scopes.MAILBOX_MANAGE))],
)
async def update_provider(
    provider_id: str,
    body: DeliverabilityProviderWrite,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityProviderResponse:
    if body.kind == "placement" and not auth.user.is_admin:
        raise AuthorizationError("Seed inbox providers require an administrator")
    provider = await get_provider(db, provider_id, user_id=auth.user.id)
    return await save_provider(db, user_id=auth.user.id, body=body, existing=provider)


@router.delete(
    "/providers/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_scope(scopes.MAILBOX_MANAGE))],
)
async def remove_provider(
    provider_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> Response:
    provider = await get_provider(db, provider_id, user_id=auth.user.id)
    await delete_provider(db, provider)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/schedules",
    response_model=list[DeliverabilityScheduleResponse],
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def schedules(
    mailbox: str = Query(..., description="Owned deliverability mailbox address"),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> list[DeliverabilityScheduleResponse]:
    await verify_mailbox_access(mailbox, auth, db)
    return await list_schedules(
        db,
        user_id=auth.user.id,
        mailbox=await get_mailbox_by_address(mailbox, db),
    )


@router.post(
    "/schedules",
    response_model=DeliverabilityScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope(scopes.MAILBOX_MANAGE))],
)
async def create_schedule(
    body: DeliverabilityScheduleWrite,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityScheduleResponse:
    await verify_mailbox_access(body.mailbox, auth, db)
    return await save_schedule(
        db,
        user_id=auth.user.id,
        mailbox=await get_mailbox_by_address(body.mailbox, db),
        body=body,
    )


@router.put(
    "/schedules/{schedule_id}",
    response_model=DeliverabilityScheduleResponse,
    dependencies=[Depends(require_scope(scopes.MAILBOX_MANAGE))],
)
async def update_schedule(
    schedule_id: str,
    body: DeliverabilityScheduleWrite,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityScheduleResponse:
    schedule = await get_schedule(db, schedule_id, user_id=auth.user.id)
    existing_mailbox = await db.get(Mailbox, schedule.mailbox_id)
    if existing_mailbox is None:
        raise AuthorizationError("The schedule mailbox no longer exists")
    _verify_record_key_access(existing_mailbox.address, auth)
    await verify_mailbox_access(body.mailbox, auth, db)
    return await save_schedule(
        db,
        user_id=auth.user.id,
        mailbox=await get_mailbox_by_address(body.mailbox, db),
        body=body,
        existing=schedule,
    )


@router.delete(
    "/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_scope(scopes.MAILBOX_MANAGE))],
)
async def remove_schedule(
    schedule_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> Response:
    schedule = await get_schedule(db, schedule_id, user_id=auth.user.id)
    mailbox = await db.get(Mailbox, schedule.mailbox_id)
    if mailbox is None:
        raise AuthorizationError("The schedule mailbox no longer exists")
    _verify_record_key_access(mailbox.address, auth)
    await delete_schedule(db, schedule)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/alerts",
    response_model=DeliverabilityAlertList,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def alerts(
    acknowledged: bool | None = Query(None),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityAlertList:
    result = await list_alerts(db, user_id=auth.user.id, acknowledged=acknowledged)
    result.alerts = [item for item in result.alerts if auth.mailbox_allowed(item.mailbox)]
    result.total = len(result.alerts)
    return result


@router.post(
    "/alerts/{alert_id}/acknowledge",
    response_model=DeliverabilityAlertResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def acknowledge(
    alert_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityAlertResponse:
    alert = await get_alert(db, alert_id, user_id=auth.user.id)
    mailbox = await db.get(Mailbox, alert.mailbox_id)
    if mailbox is None:
        raise AuthorizationError("The alert mailbox no longer exists")
    _verify_record_key_access(mailbox.address, auth)
    return await acknowledge_alert(db, alert)


@router.get(
    "/reports/{report_id}/runs",
    response_model=list[DeliverabilityRunResponse],
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def report_runs(
    report_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> list[DeliverabilityRunResponse]:
    report = await get_report_record(db, report_id, user_id=auth.user.id)
    _verify_record_key_access(report.mailbox_address, auth)
    return await list_runs_for_report(db, report_id, user_id=auth.user.id)


@router.get(
    "/runs/{run_id}",
    response_model=DeliverabilityRunResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def run_detail(
    run_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityRunResponse:
    run = await get_run(db, run_id, user_id=auth.user.id)
    report = await get_report_record(db, run.report_id, user_id=auth.user.id)
    _verify_record_key_access(report.mailbox_address, auth)
    return run


@router.get(
    "/artifacts/{artifact_id}",
    response_class=Response,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def artifact_content(
    artifact_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> Response:
    artifact = await get_artifact(db, artifact_id, user_id=auth.user.id)
    run = await get_run(db, artifact.run_id, user_id=auth.user.id)
    report = await get_report_record(db, run.report_id, user_id=auth.user.id)
    _verify_record_key_access(report.mailbox_address, auth)
    return Response(
        content=artifact.data,
        media_type=artifact.media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f'inline; filename="{artifact.filename}"',
            "ETag": f'"{artifact.sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/policies",
    response_model=list[DeliverabilityPolicyResponse],
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def policies(
    mailbox: str = Query(..., description="Owned deliverability mailbox address"),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> list[DeliverabilityPolicyResponse]:
    await verify_mailbox_access(mailbox, auth, db)
    return await list_policies(
        db,
        user_id=auth.user.id,
        mailbox=await get_mailbox_by_address(mailbox, db),
    )


@router.post(
    "/policies",
    response_model=DeliverabilityPolicyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope(scopes.MAILBOX_MANAGE))],
)
async def create_policy(
    body: DeliverabilityPolicyWrite,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityPolicyResponse:
    await verify_mailbox_access(body.mailbox, auth, db)
    mailbox = await get_mailbox_by_address(body.mailbox, db)
    return await save_policy(db, user_id=auth.user.id, mailbox=mailbox, body=body)


@router.put(
    "/policies/{policy_id}",
    response_model=DeliverabilityPolicyResponse,
    dependencies=[Depends(require_scope(scopes.MAILBOX_MANAGE))],
)
async def update_policy(
    policy_id: str,
    body: DeliverabilityPolicyWrite,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityPolicyResponse:
    policy = await get_policy(db, policy_id, user_id=auth.user.id)
    existing_mailbox = await db.get(Mailbox, policy.mailbox_id)
    if existing_mailbox is None:
        raise AuthorizationError("The policy mailbox no longer exists")
    _verify_record_key_access(existing_mailbox.address, auth)
    await verify_mailbox_access(body.mailbox, auth, db)
    mailbox = await get_mailbox_by_address(body.mailbox, db)
    return await save_policy(
        db,
        user_id=auth.user.id,
        mailbox=mailbox,
        body=body,
        existing=policy,
    )


@router.delete(
    "/policies/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_scope(scopes.MAILBOX_MANAGE))],
)
async def remove_policy(
    policy_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> Response:
    policy = await get_policy(db, policy_id, user_id=auth.user.id)
    mailbox = await db.get(Mailbox, policy.mailbox_id)
    if mailbox is None:
        raise AuthorizationError("The policy mailbox no longer exists")
    _verify_record_key_access(mailbox.address, auth)
    await delete_policy(db, policy)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/policies/{policy_id}/evaluate/{report_id}",
    response_model=DeliverabilityPolicyEvaluationResponse,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def policy_evaluation(
    policy_id: str,
    report_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityPolicyEvaluationResponse:
    policy = await get_policy(db, policy_id, user_id=auth.user.id)
    report = await get_report_record(db, report_id, user_id=auth.user.id)
    if policy.mailbox_id != report.mailbox_id:
        raise AuthorizationError("Policy and report must belong to the same mailbox")
    _verify_record_key_access(report.mailbox_address, auth)
    return await evaluate_policy(db, policy=policy, report=report)


@router.get(
    "/reports",
    response_model=DeliverabilityReportList,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def report_history(
    mailbox: str = Query(..., description="Owned mailbox address"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityReportList:
    await verify_mailbox_access(mailbox, auth, db)
    mailbox_record = await get_mailbox_by_address(mailbox, db)
    return await list_reports(
        db,
        user_id=auth.user.id,
        mailbox=mailbox_record,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/trends",
    response_model=DeliverabilityTrend,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def report_trend(
    mailbox: str = Query(..., description="Owned mailbox address"),
    limit: int = Query(100, ge=2, le=1000),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityTrend:
    await verify_mailbox_access(mailbox, auth, db)
    return await get_trend(
        db,
        user_id=auth.user.id,
        mailbox=await get_mailbox_by_address(mailbox, db),
        limit=limit,
    )


@router.get(
    "/reports/{report_id}",
    response_model=DeliverabilityReport,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def report_detail(
    report_id: str,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityReport:
    record = await get_report_record(db, report_id, user_id=auth.user.id)
    _verify_record_key_access(record.mailbox_address, auth)
    return await get_report(db, report_id, user_id=auth.user.id)


@router.get(
    "/reports/{report_id}/export",
    response_class=Response,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def export_report(
    report_id: str,
    format: str = Query("json", pattern="^(json|csv|html)$"),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> Response:
    record = await get_report_record(db, report_id, user_id=auth.user.id)
    _verify_record_key_access(record.mailbox_address, auth)
    report = await get_report(db, report_id, user_id=auth.user.id)
    filename = f"mailcue-deliverability-{report_id}"
    if format == "json":
        content = report.model_dump_json(indent=2)
        media_type = "application/json"
    elif format == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "category",
                "check_id",
                "title",
                "status",
                "points",
                "max_points",
                "summary",
                "recommendation",
                "details",
                "evidence",
            ]
        )
        for category in report.categories:
            for check in category.checks:
                writer.writerow(
                    [
                        category.id,
                        check.id,
                        check.title,
                        check.status,
                        check.points,
                        check.max_points,
                        check.summary,
                        check.recommendation or "",
                        json.dumps(check.details, ensure_ascii=False),
                        json.dumps(
                            [item.model_dump(mode="json") for item in check.evidence],
                            ensure_ascii=False,
                        ),
                    ]
                )
        content = output.getvalue()
        media_type = "text/csv"
    else:
        category_html = "".join(
            "<section><h2>"
            + html.escape(category.title)
            + "</h2>"
            + "".join(
                "<article><h3>"
                + html.escape(check.title)
                + f" <small>{html.escape(check.status)}</small></h3><p>"
                + html.escape(check.summary)
                + "</p>"
                + (
                    "<p><strong>Recommendation:</strong> "
                    + html.escape(check.recommendation)
                    + "</p>"
                    if check.recommendation
                    else ""
                )
                + "</article>"
                for check in category.checks
            )
            + "</section>"
            for category in report.categories
        )
        content = (
            "<!doctype html><html><head><meta charset='utf-8'><title>MailCue deliverability "
            + html.escape(report_id)
            + "</title><style>body{font:16px system-ui;max-width:960px;margin:40px auto;padding:0 20px}"
            "header,section{border:1px solid #ddd;border-radius:12px;padding:20px;margin:16px 0}"
            "article{border-top:1px solid #eee;padding:12px 0}small{font-weight:normal}</style></head>"
            f"<body><header><h1>Deliverability score: {report.score}/100</h1><p>"
            + html.escape(report.summary)
            + "</p></header>"
            + category_html
            + "</body></html>"
        )
        media_type = "text/html"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.{format}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put(
    "/reports/{report_id}/baseline",
    response_model=DeliverabilityReport,
    dependencies=[Depends(require_scope(scopes.MAILBOX_MANAGE))],
)
async def update_report_baseline(
    report_id: str,
    body: BaselineUpdateRequest,
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityReport:
    record = await get_report_record(db, report_id, user_id=auth.user.id)
    _verify_record_key_access(record.mailbox_address, auth)
    return await set_baseline(db, record, is_baseline=body.is_baseline)


@router.get(
    "/reports/{report_id}/comparison",
    response_model=DeliverabilityComparison,
    dependencies=[Depends(require_scope(scopes.EMAIL_READ))],
)
async def report_comparison(
    report_id: str,
    before_report_id: str | None = Query(None),
    auth: AuthContext = Depends(get_auth),
    db: AsyncSession = Depends(get_db),
) -> DeliverabilityComparison:
    after = await get_report_record(db, report_id, user_id=auth.user.id)
    _verify_record_key_access(after.mailbox_address, auth)
    before = await resolve_comparison_base(
        db,
        after,
        user_id=auth.user.id,
        before_report_id=before_report_id,
    )
    _verify_record_key_access(before.mailbox_address, auth)
    return compare_reports(before, after)
