"""Durable, tenant-scoped deliverability report operations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deliverability.links import analyze_links
from app.deliverability.models import (
    DeliverabilityAlert,
    DeliverabilityArtifact,
    DeliverabilityPolicy,
    DeliverabilityPolicyEvaluation,
    DeliverabilityProvider,
    DeliverabilityReportRecord,
    DeliverabilityRun,
    DeliverabilitySchedule,
)
from app.deliverability.network import analyze_network
from app.deliverability.placement import PlacementResult, classify_seed_account
from app.deliverability.providers import run_analysis_provider, run_preview_provider
from app.deliverability.schemas import (
    DeliverabilityAlertList,
    DeliverabilityAlertResponse,
    DeliverabilityCapabilities,
    DeliverabilityCapability,
    DeliverabilityCategoryChange,
    DeliverabilityCheckChange,
    DeliverabilityComparison,
    DeliverabilityPolicyEvaluationResponse,
    DeliverabilityPolicyResponse,
    DeliverabilityPolicyWrite,
    DeliverabilityProviderResponse,
    DeliverabilityProviderWrite,
    DeliverabilityReportList,
    DeliverabilityReportSummary,
    DeliverabilityRunResponse,
    DeliverabilityScheduleResponse,
    DeliverabilityScheduleWrite,
    DeliverabilityTrend,
    DeliverabilityTrendPoint,
)
from app.deliverability.secrets import encrypt_provider_secret
from app.deliverability.visual import (
    chromium_executable,
    image_difference_percent,
    render_email,
)
from app.emails.deliverability import DELIVERABILITY_SCORE_VERSION, score_deliverability
from app.emails.schemas import (
    DeliverabilityCategory,
    DeliverabilityCheck,
    DeliverabilityEvidence,
    DeliverabilityReport,
)
from app.exceptions import ConflictError, NotFoundError
from app.mailboxes.models import Mailbox
from app.warmup.models import WarmupAccount

_ENRICHMENT_SEMAPHORE = asyncio.Semaphore(settings.deliverability_max_concurrent_runs)


def _hydrate(record: DeliverabilityReportRecord, *, cached: bool) -> DeliverabilityReport:
    report = DeliverabilityReport.model_validate(record.report_json)
    report.report_id = record.id
    report.raw_sha256 = record.raw_sha256
    report.cached = cached
    report.is_baseline = record.is_baseline
    return report


def _summary(record: DeliverabilityReportRecord) -> DeliverabilityReportSummary:
    return DeliverabilityReportSummary(
        id=record.id,
        mailbox=record.mailbox_address,
        uid=record.uid,
        folder=record.folder,
        message_id=record.message_id,
        raw_sha256=record.raw_sha256,
        score_version=record.score_version,
        score=record.score,
        verdict=record.verdict,
        is_baseline=record.is_baseline,
        created_at=record.created_at,
    )


async def get_or_create_report(
    db: AsyncSession,
    *,
    mailbox: Mailbox,
    user_id: str,
    uid: str,
    folder: str,
    raw: bytes,
) -> DeliverabilityReport:
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    score_version = DELIVERABILITY_SCORE_VERSION
    lookup = select(DeliverabilityReportRecord).where(
        DeliverabilityReportRecord.mailbox_id == mailbox.id,
        DeliverabilityReportRecord.folder == folder,
        DeliverabilityReportRecord.uid == uid,
        DeliverabilityReportRecord.raw_sha256 == raw_sha256,
        DeliverabilityReportRecord.score_version == score_version,
    )
    existing = (await db.execute(lookup)).scalar_one_or_none()
    if existing is not None:
        return _hydrate(existing, cached=True)

    report = await asyncio.to_thread(
        score_deliverability,
        raw,
        mailbox=mailbox.address,
        uid=uid,
        folder=folder,
    )
    report.raw_sha256 = raw_sha256
    record = DeliverabilityReportRecord(
        user_id=user_id,
        mailbox_id=mailbox.id,
        mailbox_address=mailbox.address,
        folder=folder,
        uid=uid,
        message_id=report.message_id,
        raw_sha256=raw_sha256,
        score_version=report.score_version,
        score=report.score,
        verdict=report.verdict,
        report_json=report.model_dump(
            mode="json",
            exclude={"report_id", "cached", "is_baseline"},
        ),
    )
    db.add(record)
    try:
        await db.commit()
        await db.refresh(record)
    except IntegrityError:
        await db.rollback()
        concurrent = (await db.execute(lookup)).scalar_one()
        return _hydrate(concurrent, cached=True)
    report.report_id = record.id
    return report


async def get_report_record(
    db: AsyncSession, report_id: str, *, user_id: str
) -> DeliverabilityReportRecord:
    statement = select(DeliverabilityReportRecord).where(
        DeliverabilityReportRecord.id == report_id,
        DeliverabilityReportRecord.user_id == user_id,
    )
    record = (await db.execute(statement)).scalar_one_or_none()
    if record is None:
        raise NotFoundError("Deliverability report", report_id)
    return record


async def get_report(db: AsyncSession, report_id: str, *, user_id: str) -> DeliverabilityReport:
    return _hydrate(await get_report_record(db, report_id, user_id=user_id), cached=True)


async def list_reports(
    db: AsyncSession,
    *,
    user_id: str,
    mailbox: Mailbox | None,
    page: int,
    page_size: int,
) -> DeliverabilityReportList:
    filters = [DeliverabilityReportRecord.user_id == user_id]
    if mailbox is not None:
        filters.append(DeliverabilityReportRecord.mailbox_id == mailbox.id)
    total_statement = select(func.count()).select_from(DeliverabilityReportRecord).where(*filters)
    total = int((await db.execute(total_statement)).scalar_one())
    statement = (
        select(DeliverabilityReportRecord)
        .where(*filters)
        .order_by(
            DeliverabilityReportRecord.created_at.desc(),
            DeliverabilityReportRecord.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    records = list((await db.execute(statement)).scalars().all())
    return DeliverabilityReportList(
        reports=[_summary(record) for record in records],
        total=total,
        page=page,
        page_size=page_size,
        has_more=page * page_size < total,
    )


async def delete_message_reports(
    db: AsyncSession,
    *,
    user_id: str,
    mailbox_id: str,
    folder: str,
    uids: list[str],
) -> int:
    """Delete report snapshots whose source messages were removed."""
    if not uids:
        return 0
    result = await db.execute(
        delete(DeliverabilityReportRecord).where(
            DeliverabilityReportRecord.user_id == user_id,
            DeliverabilityReportRecord.mailbox_id == mailbox_id,
            DeliverabilityReportRecord.folder == folder,
            DeliverabilityReportRecord.uid.in_(uids),
        )
    )
    await db.commit()
    return result.rowcount


async def delete_mailbox_reports(db: AsyncSession, *, user_id: str, mailbox_id: str) -> int:
    """Delete every report snapshot after all mailbox messages are purged."""
    result = await db.execute(
        delete(DeliverabilityReportRecord).where(
            DeliverabilityReportRecord.user_id == user_id,
            DeliverabilityReportRecord.mailbox_id == mailbox_id,
        )
    )
    await db.commit()
    return result.rowcount


async def set_baseline(
    db: AsyncSession,
    record: DeliverabilityReportRecord,
    *,
    is_baseline: bool,
) -> DeliverabilityReport:
    if is_baseline:
        await db.execute(
            update(DeliverabilityReportRecord)
            .where(DeliverabilityReportRecord.mailbox_id == record.mailbox_id)
            .values(is_baseline=False)
        )
    record.is_baseline = is_baseline
    await db.commit()
    await db.refresh(record)
    return _hydrate(record, cached=True)


async def resolve_comparison_base(
    db: AsyncSession,
    after: DeliverabilityReportRecord,
    *,
    user_id: str,
    before_report_id: str | None,
) -> DeliverabilityReportRecord:
    if before_report_id:
        before = await get_report_record(db, before_report_id, user_id=user_id)
        if before.mailbox_id != after.mailbox_id:
            raise NotFoundError("Deliverability report", before_report_id)
        return before
    baseline = (
        (
            await db.execute(
                select(DeliverabilityReportRecord)
                .where(
                    DeliverabilityReportRecord.user_id == user_id,
                    DeliverabilityReportRecord.mailbox_id == after.mailbox_id,
                    DeliverabilityReportRecord.is_baseline.is_(True),
                    DeliverabilityReportRecord.id != after.id,
                )
                .order_by(DeliverabilityReportRecord.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if baseline is not None:
        return baseline
    previous = (
        (
            await db.execute(
                select(DeliverabilityReportRecord)
                .where(
                    DeliverabilityReportRecord.user_id == user_id,
                    DeliverabilityReportRecord.mailbox_id == after.mailbox_id,
                    DeliverabilityReportRecord.id != after.id,
                    DeliverabilityReportRecord.created_at <= after.created_at,
                )
                .order_by(
                    DeliverabilityReportRecord.created_at.desc(),
                    DeliverabilityReportRecord.id.desc(),
                )
            )
        )
        .scalars()
        .first()
    )
    if previous is None:
        raise NotFoundError("Earlier deliverability report", after.id)
    return previous


def compare_reports(
    before_record: DeliverabilityReportRecord,
    after_record: DeliverabilityReportRecord,
) -> DeliverabilityComparison:
    before = _hydrate(before_record, cached=True)
    after = _hydrate(after_record, cached=True)
    before_categories = {category.id: category for category in before.categories}
    after_categories = {category.id: category for category in after.categories}
    categories: list[DeliverabilityCategoryChange] = []
    improved = regressed = unchanged = 0
    for category_id in sorted(set(before_categories) | set(after_categories)):
        old_category = before_categories.get(category_id)
        new_category = after_categories.get(category_id)
        old_checks = {check.id: check for check in old_category.checks} if old_category else {}
        new_checks = {check.id: check for check in new_category.checks} if new_category else {}
        changes: list[DeliverabilityCheckChange] = []
        for check_id in sorted(set(old_checks) | set(new_checks)):
            old = old_checks.get(check_id)
            new = new_checks.get(check_id)
            delta = (new.points if new else 0) - (old.points if old else 0)
            if delta > 0:
                improved += 1
            elif delta < 0:
                regressed += 1
            else:
                unchanged += 1
            changes.append(
                DeliverabilityCheckChange(
                    id=check_id,
                    title=new.title if new else old.title if old else check_id,
                    before_status=old.status if old else None,
                    after_status=new.status if new else None,
                    before_points=old.points if old else None,
                    after_points=new.points if new else None,
                    points_delta=round(delta, 1),
                )
            )
        old_score = old_category.score if old_category else None
        new_score = new_category.score if new_category else None
        category_title = (
            new_category.title
            if new_category is not None
            else old_category.title
            if old_category is not None
            else category_id
        )
        categories.append(
            DeliverabilityCategoryChange(
                id=category_id,
                title=category_title,
                before_score=old_score,
                after_score=new_score,
                score_delta=(new_score - old_score)
                if new_score is not None and old_score is not None
                else None,
                check_changes=changes,
            )
        )
    return DeliverabilityComparison(
        before_report_id=before_record.id,
        after_report_id=after_record.id,
        before_score=before.score,
        after_score=after.score,
        score_delta=after.score - before.score,
        improved=improved,
        regressed=regressed,
        unchanged=unchanged,
        categories=categories,
    )


async def get_capabilities(db: AsyncSession, *, user_id: str) -> DeliverabilityCapabilities:
    """Describe real deployment capabilities without implying an external check ran."""
    enabled_providers = list(
        (
            await db.execute(
                select(DeliverabilityProvider).where(
                    DeliverabilityProvider.user_id == user_id,
                    DeliverabilityProvider.enabled.is_(True),
                )
            )
        ).scalars()
    )
    provider_kinds = {provider.kind for provider in enabled_providers}
    placement_ids: set[str] = set()
    for provider in enabled_providers:
        account_ids = provider.config_json.get("account_ids", [])
        if provider.kind == "placement" and isinstance(account_ids, list):
            placement_ids.update(
                account_id for account_id in account_ids if isinstance(account_id, str)
            )
    eligible_placement_accounts = 0
    if placement_ids:
        eligible_placement_accounts = int(
            await db.scalar(
                select(func.count())
                .select_from(WarmupAccount)
                .where(
                    WarmupAccount.id.in_(placement_ids),
                    WarmupAccount.enabled.is_(True),
                    WarmupAccount.verified.is_(True),
                )
            )
            or 0
        )

    def optional(
        capability_id: str,
        title: str,
        description: str,
        mode: Literal["local", "network", "provider"],
        enabled: bool,
    ) -> DeliverabilityCapability:
        return DeliverabilityCapability(
            id=capability_id,
            title=title,
            description=description,
            mode=mode,
            status="available" if enabled else "disabled",
            reason=None if enabled else "Disabled by server configuration.",
        )

    capabilities = [
        DeliverabilityCapability(
            id="local_analysis",
            title="Local message analysis",
            description="Authentication evidence, headers, MIME, content, and local spam filtering.",
            mode="local",
            status="available",
        ),
        optional(
            "dns_reputation",
            "DNS and reputation checks",
            "Bounded DNS policy, infrastructure, and configured blocklist checks.",
            "network",
            settings.deliverability_network_checks_enabled,
        ),
        optional(
            "link_validation",
            "Safe link validation",
            "Public destination resolution and bounded HTTP link checks.",
            "network",
            settings.deliverability_network_checks_enabled,
        ),
        DeliverabilityCapability(
            id="visual_rendering",
            title="Local visual rendering",
            description="Network-blocked desktop, tablet, and mobile screenshots in light and dark modes.",
            mode="local",
            status=(
                "disabled"
                if not settings.deliverability_visual_checks_enabled
                else "available"
                if chromium_executable() is not None
                else "unavailable"
            ),
            reason=(
                "Disabled by server configuration."
                if not settings.deliverability_visual_checks_enabled
                else None
                if chromium_executable() is not None
                else "Chromium was not found at the configured executable path."
            ),
        ),
        DeliverabilityCapability(
            id="client_previews",
            title="Real-client previews",
            description="Optional external client-preview provider adapter.",
            mode="provider",
            status="available" if "preview" in provider_kinds else "not_configured",
            reason=None
            if "preview" in provider_kinds
            else "No enabled preview provider is configured.",
        ),
        DeliverabilityCapability(
            id="inbox_placement",
            title="Seed inbox placement",
            description="Optional placement checks using inboxes controlled by the operator.",
            mode="provider",
            status=(
                "available"
                if eligible_placement_accounts > 0
                else "unavailable"
                if "placement" in provider_kinds
                else "not_configured"
            ),
            reason=(
                None
                if eligible_placement_accounts > 0
                else "The placement provider has no enabled, verified seed accounts."
                if "placement" in provider_kinds
                else "No enabled placement provider is configured."
            ),
        ),
        DeliverabilityCapability(
            id="ai_analysis",
            title="AI-assisted copy review",
            description="Optional advisory analysis from an explicitly configured HTTPS provider.",
            mode="provider",
            status="available" if "analysis" in provider_kinds else "not_configured",
            reason=None
            if "analysis" in provider_kinds
            else "No enabled analysis provider is configured.",
        ),
    ]
    return DeliverabilityCapabilities(capabilities=capabilities)


def _policy_response(
    policy: DeliverabilityPolicy, *, mailbox: str
) -> DeliverabilityPolicyResponse:
    return DeliverabilityPolicyResponse(
        id=policy.id,
        name=policy.name,
        mailbox=mailbox,
        enabled=policy.enabled,
        minimum_score=policy.minimum_score,
        maximum_regression=policy.maximum_regression,
        fail_on_statuses=policy.fail_on_statuses,
        required_check_ids=policy.required_check_ids,
        required_capabilities=policy.required_capabilities,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


async def list_policies(
    db: AsyncSession, *, user_id: str, mailbox: Mailbox
) -> list[DeliverabilityPolicyResponse]:
    rows = list(
        (
            await db.execute(
                select(DeliverabilityPolicy)
                .where(
                    DeliverabilityPolicy.user_id == user_id,
                    DeliverabilityPolicy.mailbox_id == mailbox.id,
                )
                .order_by(DeliverabilityPolicy.name, DeliverabilityPolicy.id)
            )
        )
        .scalars()
        .all()
    )
    return [_policy_response(row, mailbox=mailbox.address) for row in rows]


async def get_policy(db: AsyncSession, policy_id: str, *, user_id: str) -> DeliverabilityPolicy:
    row = (
        await db.execute(
            select(DeliverabilityPolicy).where(
                DeliverabilityPolicy.id == policy_id,
                DeliverabilityPolicy.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Deliverability policy", policy_id)
    return row


async def save_policy(
    db: AsyncSession,
    *,
    user_id: str,
    mailbox: Mailbox,
    body: DeliverabilityPolicyWrite,
    existing: DeliverabilityPolicy | None = None,
) -> DeliverabilityPolicyResponse:
    row = existing or DeliverabilityPolicy(
        id=str(uuid.uuid4()), user_id=user_id, mailbox_id=mailbox.id
    )
    row.mailbox_id = mailbox.id
    row.name = body.name
    row.enabled = body.enabled
    row.minimum_score = body.minimum_score
    row.maximum_regression = body.maximum_regression
    row.fail_on_statuses = list(body.fail_on_statuses)
    row.required_check_ids = body.required_check_ids
    row.required_capabilities = body.required_capabilities
    if existing is None:
        db.add(row)
    try:
        await db.commit()
        await db.refresh(row)
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(f"Deliverability policy '{body.name}' already exists") from exc
    return _policy_response(row, mailbox=mailbox.address)


async def delete_policy(db: AsyncSession, policy: DeliverabilityPolicy) -> None:
    await db.delete(policy)
    await db.commit()


async def evaluate_policy(
    db: AsyncSession,
    *,
    policy: DeliverabilityPolicy,
    report: DeliverabilityReportRecord,
) -> DeliverabilityPolicyEvaluationResponse:
    existing = (
        await db.execute(
            select(DeliverabilityPolicyEvaluation).where(
                DeliverabilityPolicyEvaluation.policy_id == policy.id,
                DeliverabilityPolicyEvaluation.report_id == report.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        result = existing.result_json
        return DeliverabilityPolicyEvaluationResponse(
            id=existing.id,
            policy_id=policy.id,
            report_id=report.id,
            passed=existing.passed,
            score=report.score,
            score_delta=result.get("score_delta"),
            reasons=result.get("reasons", []),
            created_at=existing.created_at,
        )

    parsed = _hydrate(report, cached=True)
    checks = {check.id: check for category in parsed.categories for check in category.checks}
    reasons: list[str] = []
    if report.score < policy.minimum_score:
        reasons.append(f"Score {report.score} is below the required {policy.minimum_score}.")
    failing = sorted(
        check.title for check in checks.values() if check.status in policy.fail_on_statuses
    )
    if failing:
        reasons.append("Checks with blocked statuses: " + ", ".join(failing) + ".")
    for check_id in policy.required_check_ids:
        check = checks.get(check_id)
        if check is None:
            reasons.append(f"Required check '{check_id}' is missing.")
        elif check.status != "pass":
            reasons.append(f"Required check '{check_id}' did not pass.")

    capabilities = await get_capabilities(db, user_id=policy.user_id)
    available = {
        capability.id
        for capability in capabilities.capabilities
        if capability.status == "available"
    }
    for capability_id in policy.required_capabilities:
        if capability_id not in available:
            reasons.append(f"Required capability '{capability_id}' is unavailable.")

    score_delta: int | None = None
    try:
        before = await resolve_comparison_base(
            db, report, user_id=policy.user_id, before_report_id=None
        )
    except NotFoundError:
        pass
    else:
        score_delta = report.score - before.score
        if score_delta < -policy.maximum_regression:
            reasons.append(
                f"Score regressed by {-score_delta} points, above the allowed "
                f"{policy.maximum_regression}."
            )

    now = datetime.now(UTC)
    result_json = {"score_delta": score_delta, "reasons": reasons}
    evaluation = DeliverabilityPolicyEvaluation(
        id=str(uuid.uuid4()),
        policy_id=policy.id,
        report_id=report.id,
        passed=not reasons,
        result_json=result_json,
        created_at=now,
    )
    db.add(evaluation)
    if reasons:
        db.add(
            DeliverabilityAlert(
                id=str(uuid.uuid4()),
                user_id=policy.user_id,
                mailbox_id=policy.mailbox_id,
                report_id=report.id,
                policy_id=policy.id,
                deduplication_key=f"policy:{policy.id}:report:{report.id}",
                alert_type="policy_failed",
                severity="error",
                title=f"Deliverability policy failed: {policy.name}"[:255],
                detail=" ".join(reasons)[:4000],
                created_at=now,
            )
        )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return await evaluate_policy(db, policy=policy, report=report)
    return DeliverabilityPolicyEvaluationResponse(
        id=evaluation.id,
        policy_id=policy.id,
        report_id=report.id,
        passed=evaluation.passed,
        score=report.score,
        score_delta=score_delta,
        reasons=reasons,
        created_at=now,
    )


def _run_response(run: DeliverabilityRun) -> DeliverabilityRunResponse:
    return DeliverabilityRunResponse(
        id=run.id,
        report_id=run.report_id,
        status=run.status,
        requested_checks=run.requested_checks,
        capabilities=DeliverabilityCapabilities.model_validate(run.capability_snapshot),
        categories=run.result_json.get("categories", []),
        error_code=run.error_code,
        error_detail=run.error_detail,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


async def _baseline_visual_artifacts(
    db: AsyncSession, report: DeliverabilityReportRecord
) -> dict[str, DeliverabilityArtifact]:
    baseline = (
        await db.execute(
            select(DeliverabilityReportRecord).where(
                DeliverabilityReportRecord.mailbox_id == report.mailbox_id,
                DeliverabilityReportRecord.is_baseline.is_(True),
                DeliverabilityReportRecord.id != report.id,
            )
        )
    ).scalar_one_or_none()
    if baseline is None:
        return {}
    artifacts = list(
        (
            await db.execute(
                select(DeliverabilityArtifact)
                .join(DeliverabilityRun, DeliverabilityArtifact.run_id == DeliverabilityRun.id)
                .where(
                    DeliverabilityRun.report_id == baseline.id,
                    DeliverabilityArtifact.kind == "screenshot",
                )
                .order_by(DeliverabilityArtifact.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    by_name: dict[str, DeliverabilityArtifact] = {}
    for artifact in artifacts:
        by_name.setdefault(artifact.filename, artifact)
    return by_name


async def _execute_run(
    db: AsyncSession,
    *,
    report: DeliverabilityReportRecord,
    raw: bytes,
    requested_checks: list[str],
) -> DeliverabilityRunResponse:
    capabilities = await get_capabilities(db, user_id=report.user_id)
    capability_by_id = {item.id: item for item in capabilities.capabilities}
    now = datetime.now(UTC)
    run = DeliverabilityRun(
        id=str(uuid.uuid4()),
        user_id=report.user_id,
        mailbox_id=report.mailbox_id,
        report_id=report.id,
        status="running",
        requested_checks=requested_checks,
        capability_snapshot=capabilities.model_dump(mode="json"),
        result_json={},
        created_at=now,
        started_at=now,
    )
    db.add(run)
    await db.commit()

    capability_ids = {
        "dns": "dns_reputation",
        "reputation": "dns_reputation",
        "links": "link_validation",
        "visual": "visual_rendering",
        "placement": "inbox_placement",
        "client_previews": "client_previews",
        "ai_analysis": "ai_analysis",
    }
    available = [
        check_id
        for check_id in requested_checks
        if capability_by_id.get(capability_ids[check_id])
        and capability_by_id[capability_ids[check_id]].status == "available"
    ]
    unavailable = [check_id for check_id in requested_checks if check_id not in available]
    categories: list[DeliverabilityCategory] = []
    try:
        if {"dns", "reputation"} & set(available):
            network_categories = await analyze_network(
                raw,
                sender_domain=str(report.report_json.get("sender_domain") or "") or None,
            )
            categories.extend(
                category for category in network_categories if category.id in set(requested_checks)
            )
        if "links" in available:
            categories.append(await analyze_links(raw))
        if "visual" in available:
            rendered = await render_email(raw)
            baseline_artifacts = await _baseline_visual_artifacts(db, report)
            evidence = []
            changed_variants = 0
            render_variants = 0
            for item in rendered:
                artifact_id = str(uuid.uuid4())
                db.add(
                    DeliverabilityArtifact(
                        id=artifact_id,
                        user_id=report.user_id,
                        run_id=run.id,
                        kind="screenshot",
                        filename=f"{item.name}.png",
                        media_type="image/png",
                        sha256=hashlib.sha256(item.data).hexdigest(),
                        width=item.width,
                        height=item.height,
                        data=item.data,
                    )
                )
                baseline_artifact = baseline_artifacts.get(f"{item.name}.png")
                difference: float | None = None
                if baseline_artifact is not None:
                    try:
                        difference = image_difference_percent(baseline_artifact.data, item.data)
                    except (OSError, ValueError):
                        difference = None
                if difference is not None and difference > 1:
                    changed_variants += 1
                if item.name.startswith("attention-"):
                    description = (
                        f"{item.width} by {item.height} deterministic contrast and edge "
                        "saliency estimate. This is a design aid, not measured eye tracking."
                    )
                else:
                    render_variants += 1
                    description = f"{item.width} by {item.height} network-blocked local render."
                if difference is not None:
                    description += f" Pixel difference from baseline: {difference:g}%."
                evidence.append(
                    DeliverabilityEvidence(
                        code=item.name,
                        title=item.name.replace("-", " ").title(),
                        value=f"/api/v1/deliverability/artifacts/{artifact_id}",
                        score=difference,
                        description=description,
                    )
                )
            visual_check = DeliverabilityCheck(
                id="visual_rendering",
                category="visual",
                title="Local visual rendering",
                status="warning" if changed_variants else "pass" if rendered else "info",
                summary=(
                    f"{changed_variants} render variant(s) differ materially from the baseline."
                    if changed_variants
                    else (
                        f"Generated {render_variants} desktop, tablet, and mobile light/dark "
                        "renders plus local attention estimates."
                    )
                    if rendered
                    else "The message has no HTML body to render."
                ),
                evidence=evidence,
                recommendation="Review the screenshots against the selected baseline."
                if changed_variants
                else None,
                points=2 if changed_variants else 4 if rendered else 0,
                max_points=4 if rendered else 0,
            )
            categories.append(
                DeliverabilityCategory(
                    id="visual",
                    title="Visual rendering",
                    score=round(visual_check.points / visual_check.max_points * 100)
                    if visual_check.max_points
                    else None,
                    points=visual_check.points,
                    max_points=visual_check.max_points,
                    checks=[visual_check],
                )
            )
        if "client_previews" in available:
            provider = (
                await db.execute(
                    select(DeliverabilityProvider)
                    .where(
                        DeliverabilityProvider.user_id == report.user_id,
                        DeliverabilityProvider.kind == "preview",
                        DeliverabilityProvider.enabled.is_(True),
                    )
                    .order_by(DeliverabilityProvider.name, DeliverabilityProvider.id)
                    .limit(1)
                )
            ).scalar_one()
            try:
                previews = await run_preview_provider(provider, raw)
            except Exception as exc:
                provider.last_status = "error"
                provider.last_error = f"{exc.__class__.__name__}: preview request failed"
                provider.last_checked_at = datetime.now(UTC)
                raise
            provider.last_status = "healthy"
            provider.last_error = None
            provider.last_checked_at = datetime.now(UTC)
            preview_evidence = []
            successful = 0
            for preview in previews:
                status_ok = preview.status.lower() in {"complete", "passed", "ready", "success"}
                successful += status_ok
                value: str = preview.status
                if preview.data is not None and preview.media_type is not None:
                    artifact_id = str(uuid.uuid4())
                    extension = "png" if preview.media_type == "image/png" else "jpg"
                    db.add(
                        DeliverabilityArtifact(
                            id=artifact_id,
                            user_id=report.user_id,
                            run_id=run.id,
                            kind="client_preview",
                            filename=f"preview-{artifact_id}.{extension}",
                            media_type=preview.media_type,
                            sha256=hashlib.sha256(preview.data).hexdigest(),
                            data=preview.data,
                        )
                    )
                    value = f"/api/v1/deliverability/artifacts/{artifact_id}"
                preview_evidence.append(
                    DeliverabilityEvidence(
                        code=f"{preview.client}:{preview.platform}:{preview.theme}"[:255],
                        title=f"{preview.client} {preview.platform} {preview.theme}".strip(),
                        value=value,
                        description=preview.description or f"Provider status: {preview.status}",
                    )
                )
            preview_points = round(5 * successful / len(previews), 1)
            preview_check = DeliverabilityCheck(
                id="client_previews",
                category="client_previews",
                title="Real-client previews",
                status="pass" if successful == len(previews) else "warning",
                summary=f"The configured provider returned {len(previews)} client preview(s).",
                evidence=preview_evidence,
                points=preview_points,
                max_points=5,
                recommendation="Review provider warnings and failed client renders."
                if successful != len(previews)
                else None,
            )
            categories.append(
                DeliverabilityCategory(
                    id="client_previews",
                    title="Real-client previews",
                    score=round(preview_points / 5 * 100),
                    points=preview_points,
                    max_points=5,
                    checks=[preview_check],
                )
            )
        if "ai_analysis" in available:
            provider = (
                await db.execute(
                    select(DeliverabilityProvider)
                    .where(
                        DeliverabilityProvider.user_id == report.user_id,
                        DeliverabilityProvider.kind == "analysis",
                        DeliverabilityProvider.enabled.is_(True),
                    )
                    .order_by(DeliverabilityProvider.name, DeliverabilityProvider.id)
                    .limit(1)
                )
            ).scalar_one()
            try:
                analysis = await run_analysis_provider(provider, raw)
            except Exception as exc:
                provider.last_status = "error"
                provider.last_error = f"{exc.__class__.__name__}: analysis request failed"
                provider.last_checked_at = datetime.now(UTC)
                raise
            provider.last_status = "healthy"
            provider.last_error = None
            provider.last_checked_at = datetime.now(UTC)
            evidence = [
                DeliverabilityEvidence(
                    code=f"finding-{index}",
                    title=finding.title,
                    value=finding.severity,
                    description=finding.detail or None,
                    recommendation=finding.recommendation or None,
                )
                for index, finding in enumerate(analysis.findings, start=1)
            ]
            analysis_check = DeliverabilityCheck(
                id="ai_analysis",
                category="ai_analysis",
                title="AI-assisted copy review",
                status="info",
                summary=analysis.summary
                or f"The configured provider returned {len(evidence)} advisory finding(s).",
                evidence=evidence,
                recommendation=None,
                points=0,
                max_points=0,
            )
            categories.append(
                DeliverabilityCategory(
                    id="ai_analysis",
                    title="AI-assisted copy review",
                    score=None,
                    points=0,
                    max_points=0,
                    checks=[analysis_check],
                )
            )
        if "placement" in available:
            provider = (
                await db.execute(
                    select(DeliverabilityProvider)
                    .where(
                        DeliverabilityProvider.user_id == report.user_id,
                        DeliverabilityProvider.kind == "placement",
                        DeliverabilityProvider.enabled.is_(True),
                    )
                    .order_by(DeliverabilityProvider.name, DeliverabilityProvider.id)
                    .limit(1)
                )
            ).scalar_one()
            account_ids_value = provider.config_json.get("account_ids", [])
            account_ids = (
                [str(value) for value in account_ids_value]
                if isinstance(account_ids_value, list)
                else []
            )
            folders_value = provider.config_json.get(
                "folders", ["INBOX", "Spam", "Junk", "Promotions"]
            )
            folders = (
                [str(value)[:255] for value in folders_value]
                if isinstance(folders_value, list)
                else ["INBOX", "Spam", "Junk", "Promotions"]
            )
            accounts = list(
                (
                    await db.execute(
                        select(WarmupAccount).where(
                            WarmupAccount.id.in_(account_ids),
                            WarmupAccount.enabled.is_(True),
                            WarmupAccount.verified.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            by_id = {account.id: account for account in accounts}
            ordered_accounts = [by_id[item] for item in account_ids if item in by_id]
            if not report.message_id:
                raise RuntimeError("Seed placement requires a Message-ID")
            semaphore = asyncio.Semaphore(settings.deliverability_network_concurrency)

            async def classify(account: WarmupAccount) -> PlacementResult:
                async with semaphore:
                    return await classify_seed_account(
                        account, message_id=report.message_id, folders=folders
                    )

            placements = await asyncio.gather(*(classify(account) for account in ordered_accounts))
            missing_accounts = [item for item in account_ids if item not in by_id]
            placement_evidence = [
                DeliverabilityEvidence(
                    code=result.provider,
                    title=f"{result.provider}: {result.email}",
                    value=result.placement,
                    description=result.detail,
                )
                for result in placements
            ]
            placement_evidence.extend(
                DeliverabilityEvidence(
                    code="unavailable",
                    title=f"Seed account {account_id}",
                    value="unavailable",
                    description="The seed account is missing, disabled, or not verified.",
                )
                for account_id in missing_accounts
            )
            classified = [result for result in placements if result.placement != "unavailable"]
            inbox_count = sum(result.placement == "inbox" for result in classified)
            spam_count = sum(result.placement == "spam" for result in classified)
            points = round(5 * inbox_count / len(classified), 1) if classified else 0
            placement_check = DeliverabilityCheck(
                id="seed_placement",
                category="placement",
                title="Seed inbox placement",
                status=(
                    "fail"
                    if spam_count
                    else "pass"
                    if classified and inbox_count == len(classified)
                    else "warning"
                    if classified
                    else "info"
                ),
                summary=(
                    f"Found the message in {inbox_count} inbox(es), with {spam_count} spam placement(s)."
                    if classified
                    else "No configured seed inbox could provide a placement result."
                ),
                evidence=placement_evidence,
                points=points,
                max_points=5 if classified else 0,
                recommendation="Investigate provider-specific spam or missing placements."
                if spam_count or inbox_count != len(classified)
                else None,
            )
            categories.append(
                DeliverabilityCategory(
                    id="placement",
                    title="Seed inbox placement",
                    score=round(points / 5 * 100) if classified else None,
                    points=points,
                    max_points=5 if classified else 0,
                    checks=[placement_check],
                )
            )
        run.status = "completed" if not unavailable else "partial"
        run.result_json = {
            "categories": [category.model_dump(mode="json") for category in categories]
        }
        if unavailable:
            run.error_code = "capability_unavailable"
            run.error_detail = "Unavailable checks: " + ", ".join(sorted(unavailable))
    except Exception as exc:
        run.status = "failed"
        run.error_code = "enrichment_failed"
        run.error_detail = f"{exc.__class__.__name__}: network enrichment failed"
    run.completed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(run)
    return _run_response(run)


async def execute_run(
    db: AsyncSession,
    *,
    report: DeliverabilityReportRecord,
    raw: bytes,
    requested_checks: list[str],
) -> DeliverabilityRunResponse:
    async with _ENRICHMENT_SEMAPHORE:
        return await _execute_run(
            db,
            report=report,
            raw=raw,
            requested_checks=requested_checks,
        )


async def get_run(db: AsyncSession, run_id: str, *, user_id: str) -> DeliverabilityRunResponse:
    run = (
        await db.execute(
            select(DeliverabilityRun).where(
                DeliverabilityRun.id == run_id,
                DeliverabilityRun.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Deliverability run", run_id)
    return _run_response(run)


async def list_runs_for_report(
    db: AsyncSession, report_id: str, *, user_id: str
) -> list[DeliverabilityRunResponse]:
    runs = list(
        (
            await db.execute(
                select(DeliverabilityRun)
                .where(
                    DeliverabilityRun.report_id == report_id,
                    DeliverabilityRun.user_id == user_id,
                )
                .order_by(DeliverabilityRun.created_at.desc(), DeliverabilityRun.id.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return [_run_response(run) for run in runs]


async def get_artifact(
    db: AsyncSession, artifact_id: str, *, user_id: str
) -> DeliverabilityArtifact:
    artifact = (
        await db.execute(
            select(DeliverabilityArtifact).where(
                DeliverabilityArtifact.id == artifact_id,
                DeliverabilityArtifact.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise NotFoundError("Deliverability artifact", artifact_id)
    return artifact


async def get_trend(
    db: AsyncSession, *, user_id: str, mailbox: Mailbox, limit: int
) -> DeliverabilityTrend:
    rows = list(
        (
            await db.execute(
                select(DeliverabilityReportRecord)
                .where(
                    DeliverabilityReportRecord.user_id == user_id,
                    DeliverabilityReportRecord.mailbox_id == mailbox.id,
                )
                .order_by(
                    DeliverabilityReportRecord.created_at.desc(),
                    DeliverabilityReportRecord.id.desc(),
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    rows.reverse()
    scores = [row.score for row in rows]
    return DeliverabilityTrend(
        mailbox=mailbox.address,
        points=[
            DeliverabilityTrendPoint(
                report_id=row.id,
                score=row.score,
                verdict=row.verdict,
                created_at=row.created_at,
            )
            for row in rows
        ],
        count=len(rows),
        average_score=round(sum(scores) / len(scores), 1) if scores else None,
        minimum_score=min(scores) if scores else None,
        maximum_score=max(scores) if scores else None,
        score_delta=scores[-1] - scores[0] if len(scores) > 1 else None,
    )


def _provider_response(provider: DeliverabilityProvider) -> DeliverabilityProviderResponse:
    return DeliverabilityProviderResponse(
        id=provider.id,
        name=provider.name,
        kind=provider.kind,
        adapter=provider.adapter,
        enabled=provider.enabled,
        config=provider.config_json,
        has_secret=bool(provider.secret_ciphertext),
        last_status=provider.last_status,
        last_error=provider.last_error,
        last_checked_at=provider.last_checked_at,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


def _validate_provider(body: DeliverabilityProviderWrite) -> None:
    pairs = {
        ("preview", "generic_http_preview"),
        ("placement", "seed_imap"),
        ("analysis", "generic_http_analysis"),
    }
    if (body.kind, body.adapter) not in pairs:
        raise ConflictError("Provider kind does not match its adapter")
    if len(json.dumps(body.config)) > 16_384:
        raise ConflictError("Provider configuration is too large")
    if body.adapter in {"generic_http_preview", "generic_http_analysis"}:
        parsed = urlsplit(str(body.config.get("base_url", "")))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ConflictError("Provider base_url must be a credential-free HTTPS URL")
        if parsed.port not in {None, 443}:
            raise ConflictError("Provider base_url must use port 443")
    if body.adapter == "seed_imap":
        account_ids = body.config.get("account_ids")
        if not isinstance(account_ids, list) or not 1 <= len(account_ids) <= 50:
            raise ConflictError("Seed IMAP providers require 1 to 50 account_ids")
        if any(not isinstance(value, str) or not value.strip() for value in account_ids):
            raise ConflictError("Seed IMAP account_ids must be non-empty strings")
        folders = body.config.get("folders", ["INBOX", "Spam", "Junk", "Promotions"])
        if not isinstance(folders, list) or not 1 <= len(folders) <= 20:
            raise ConflictError("Seed IMAP folders must contain 1 to 20 names")
        if any(
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 255
            or any(ord(character) < 32 for character in value)
            for value in folders
        ):
            raise ConflictError("Seed IMAP folders contain an invalid name")


async def list_providers(
    db: AsyncSession, *, user_id: str
) -> list[DeliverabilityProviderResponse]:
    providers = list(
        (
            await db.execute(
                select(DeliverabilityProvider)
                .where(DeliverabilityProvider.user_id == user_id)
                .order_by(DeliverabilityProvider.name, DeliverabilityProvider.id)
            )
        )
        .scalars()
        .all()
    )
    return [_provider_response(provider) for provider in providers]


async def get_provider(
    db: AsyncSession, provider_id: str, *, user_id: str
) -> DeliverabilityProvider:
    provider = (
        await db.execute(
            select(DeliverabilityProvider).where(
                DeliverabilityProvider.id == provider_id,
                DeliverabilityProvider.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if provider is None:
        raise NotFoundError("Deliverability provider", provider_id)
    return provider


async def save_provider(
    db: AsyncSession,
    *,
    user_id: str,
    body: DeliverabilityProviderWrite,
    existing: DeliverabilityProvider | None = None,
) -> DeliverabilityProviderResponse:
    _validate_provider(body)
    provider = existing or DeliverabilityProvider(id=str(uuid.uuid4()), user_id=user_id)
    provider.name = body.name
    provider.kind = body.kind
    provider.adapter = body.adapter
    provider.enabled = body.enabled
    provider.config_json = dict(body.config)
    if body.secret is not None:
        provider.secret_ciphertext = encrypt_provider_secret(body.secret) if body.secret else ""
    if existing is None:
        db.add(provider)
    try:
        await db.commit()
        await db.refresh(provider)
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(f"Deliverability provider '{body.name}' already exists") from exc
    return _provider_response(provider)


async def delete_provider(db: AsyncSession, provider: DeliverabilityProvider) -> None:
    await db.delete(provider)
    await db.commit()


def _schedule_response(
    schedule: DeliverabilitySchedule, *, mailbox: str
) -> DeliverabilityScheduleResponse:
    return DeliverabilityScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        mailbox=mailbox,
        enabled=schedule.enabled,
        interval_minutes=schedule.interval_minutes,
        checks=schedule.requested_checks,
        policy_id=schedule.policy_id,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
    )


async def list_schedules(
    db: AsyncSession, *, user_id: str, mailbox: Mailbox
) -> list[DeliverabilityScheduleResponse]:
    rows = list(
        (
            await db.execute(
                select(DeliverabilitySchedule)
                .where(
                    DeliverabilitySchedule.user_id == user_id,
                    DeliverabilitySchedule.mailbox_id == mailbox.id,
                )
                .order_by(DeliverabilitySchedule.name, DeliverabilitySchedule.id)
            )
        )
        .scalars()
        .all()
    )
    return [_schedule_response(row, mailbox=mailbox.address) for row in rows]


async def get_schedule(
    db: AsyncSession, schedule_id: str, *, user_id: str
) -> DeliverabilitySchedule:
    row = (
        await db.execute(
            select(DeliverabilitySchedule).where(
                DeliverabilitySchedule.id == schedule_id,
                DeliverabilitySchedule.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Deliverability schedule", schedule_id)
    return row


async def save_schedule(
    db: AsyncSession,
    *,
    user_id: str,
    mailbox: Mailbox,
    body: DeliverabilityScheduleWrite,
    existing: DeliverabilitySchedule | None = None,
) -> DeliverabilityScheduleResponse:
    if body.policy_id:
        policy = await get_policy(db, body.policy_id, user_id=user_id)
        if policy.mailbox_id != mailbox.id:
            raise ConflictError("Schedule policy must belong to the same mailbox")
    now = datetime.now(UTC)
    row = existing or DeliverabilitySchedule(
        id=str(uuid.uuid4()), user_id=user_id, mailbox_id=mailbox.id
    )
    was_enabled = row.enabled if existing is not None else False
    row.mailbox_id = mailbox.id
    row.policy_id = body.policy_id
    row.name = body.name
    row.enabled = body.enabled
    row.interval_minutes = body.interval_minutes
    row.requested_checks = list(body.checks)
    if body.enabled and (not was_enabled or row.next_run_at is None):
        row.next_run_at = now + timedelta(minutes=body.interval_minutes)
    elif not body.enabled:
        row.next_run_at = None
    if existing is None:
        db.add(row)
    try:
        await db.commit()
        await db.refresh(row)
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(f"Deliverability schedule '{body.name}' already exists") from exc
    return _schedule_response(row, mailbox=mailbox.address)


async def delete_schedule(db: AsyncSession, schedule: DeliverabilitySchedule) -> None:
    await db.delete(schedule)
    await db.commit()


def _alert_response(alert: DeliverabilityAlert, *, mailbox: str) -> DeliverabilityAlertResponse:
    return DeliverabilityAlertResponse(
        id=alert.id,
        mailbox=mailbox,
        report_id=alert.report_id,
        run_id=alert.run_id,
        policy_id=alert.policy_id,
        alert_type=alert.alert_type,
        severity=alert.severity,
        title=alert.title,
        detail=alert.detail,
        acknowledged=alert.acknowledged,
        created_at=alert.created_at,
        acknowledged_at=alert.acknowledged_at,
    )


async def list_alerts(
    db: AsyncSession, *, user_id: str, acknowledged: bool | None
) -> DeliverabilityAlertList:
    filters = [DeliverabilityAlert.user_id == user_id]
    if acknowledged is not None:
        filters.append(DeliverabilityAlert.acknowledged.is_(acknowledged))
    rows = list(
        (
            await db.execute(
                select(DeliverabilityAlert, Mailbox.address)
                .join(Mailbox, Mailbox.id == DeliverabilityAlert.mailbox_id)
                .where(*filters)
                .order_by(DeliverabilityAlert.created_at.desc(), DeliverabilityAlert.id.desc())
                .limit(500)
            )
        ).all()
    )
    return DeliverabilityAlertList(
        alerts=[_alert_response(alert, mailbox=mailbox) for alert, mailbox in rows],
        total=len(rows),
    )


async def get_alert(db: AsyncSession, alert_id: str, *, user_id: str) -> DeliverabilityAlert:
    alert = (
        await db.execute(
            select(DeliverabilityAlert).where(
                DeliverabilityAlert.id == alert_id,
                DeliverabilityAlert.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if alert is None:
        raise NotFoundError("Deliverability alert", alert_id)
    return alert


async def acknowledge_alert(
    db: AsyncSession, alert: DeliverabilityAlert
) -> DeliverabilityAlertResponse:
    mailbox = await db.get(Mailbox, alert.mailbox_id)
    if mailbox is None:
        raise NotFoundError("Mailbox", alert.mailbox_id)
    alert.acknowledged = True
    alert.acknowledged_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(alert)
    return _alert_response(alert, mailbox=mailbox.address)
