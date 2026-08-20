"""Low-frequency scheduler for recurring latest-message deliverability runs."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update

from app.config import settings
from app.database import AsyncSessionLocal, dml_rowcount
from app.deliverability.models import (
    DeliverabilityAlert,
    DeliverabilityArtifact,
    DeliverabilityPolicy,
    DeliverabilityReportRecord,
    DeliverabilityRun,
    DeliverabilitySchedule,
)
from app.deliverability.service import evaluate_policy, execute_run, get_or_create_report
from app.emails.service import get_email_raw, list_emails
from app.mailboxes.models import Mailbox

logger = logging.getLogger("mailcue.deliverability.scheduler")


async def _prune_expired_data() -> tuple[int, int]:
    now = datetime.now(UTC)
    artifacts_deleted = 0
    reports_deleted = 0
    async with AsyncSessionLocal() as db:
        if settings.deliverability_artifact_retention_days:
            cutoff = now - timedelta(days=settings.deliverability_artifact_retention_days)
            baseline_run_ids = (
                select(DeliverabilityRun.id)
                .join(
                    DeliverabilityReportRecord,
                    DeliverabilityRun.report_id == DeliverabilityReportRecord.id,
                )
                .where(DeliverabilityReportRecord.is_baseline.is_(True))
            )
            result = await db.execute(
                delete(DeliverabilityArtifact).where(
                    DeliverabilityArtifact.created_at < cutoff,
                    DeliverabilityArtifact.run_id.not_in(baseline_run_ids),
                )
            )
            artifacts_deleted = dml_rowcount(result)
        if settings.deliverability_report_retention_days:
            cutoff = now - timedelta(days=settings.deliverability_report_retention_days)
            result = await db.execute(
                delete(DeliverabilityReportRecord).where(
                    DeliverabilityReportRecord.created_at < cutoff,
                    DeliverabilityReportRecord.is_baseline.is_(False),
                )
            )
            reports_deleted = dml_rowcount(result)
        await db.commit()
    return reports_deleted, artifacts_deleted


async def _claim_due_schedule() -> tuple[DeliverabilitySchedule, Mailbox, datetime] | None:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        schedule = (
            await db.execute(
                select(DeliverabilitySchedule)
                .where(
                    DeliverabilitySchedule.enabled.is_(True),
                    DeliverabilitySchedule.next_run_at.is_not(None),
                    DeliverabilitySchedule.next_run_at <= now,
                )
                .order_by(DeliverabilitySchedule.next_run_at, DeliverabilitySchedule.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if schedule is None:
            return None
        expected_next_run = schedule.next_run_at
        if expected_next_run is None:
            return None
        claimed_at = now
        claim = await db.execute(
            update(DeliverabilitySchedule)
            .where(
                DeliverabilitySchedule.id == schedule.id,
                DeliverabilitySchedule.enabled.is_(True),
                DeliverabilitySchedule.next_run_at == expected_next_run,
            )
            .values(
                last_run_at=claimed_at,
                next_run_at=claimed_at + timedelta(minutes=schedule.interval_minutes),
            )
        )
        if dml_rowcount(claim) != 1:
            await db.rollback()
            return None
        await db.commit()
        await db.refresh(schedule)
        mailbox = await db.get(Mailbox, schedule.mailbox_id)
        if mailbox is None or not mailbox.is_active:
            schedule.enabled = False
            schedule.next_run_at = None
            await db.commit()
            return None
        return schedule, mailbox, claimed_at


async def _create_schedule_alert(
    schedule: DeliverabilitySchedule,
    *,
    claimed_at: datetime,
    alert_type: str,
    severity: str,
    title: str,
    detail: str,
    report_id: str | None = None,
    run_id: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            DeliverabilityAlert(
                id=str(uuid.uuid4()),
                user_id=schedule.user_id,
                mailbox_id=schedule.mailbox_id,
                report_id=report_id,
                run_id=run_id,
                policy_id=schedule.policy_id,
                deduplication_key=(
                    f"schedule:{schedule.id}:{alert_type}:{claimed_at.isoformat(timespec='minutes')}"
                ),
                alert_type=alert_type,
                severity=severity,
                title=title[:255],
                detail=detail[:4000],
            )
        )
        await db.commit()


async def _run_schedule(
    schedule: DeliverabilitySchedule, mailbox: Mailbox, claimed_at: datetime
) -> None:
    try:
        messages = await list_emails(mailbox.address, page=1, per_page=1)
        if not messages.emails:
            await _create_schedule_alert(
                schedule,
                claimed_at=claimed_at,
                alert_type="schedule_empty",
                severity="warning",
                title=f"No message available for schedule: {schedule.name}",
                detail="The mailbox had no message to analyze at the scheduled time.",
            )
            return
        message = messages.emails[0]
        raw = await get_email_raw(mailbox.address, message.uid, "INBOX")
        if len(raw) > settings.deliverability_max_message_bytes:
            raise RuntimeError("Latest message exceeds the analysis size limit")
        async with AsyncSessionLocal() as db:
            attached_mailbox = await db.get(Mailbox, mailbox.id)
            if attached_mailbox is None:
                return
            report = await get_or_create_report(
                db,
                mailbox=attached_mailbox,
                user_id=schedule.user_id,
                uid=message.uid,
                folder="INBOX",
                raw=raw,
            )
            if report.report_id is None:
                raise RuntimeError("Scheduled report was not persisted")
            report_record = await db.get(DeliverabilityReportRecord, report.report_id)
            if report_record is None:
                raise RuntimeError("Scheduled report could not be reloaded")
            run_id: str | None = None
            if schedule.requested_checks:
                run = await execute_run(
                    db,
                    report=report_record,
                    raw=raw,
                    requested_checks=schedule.requested_checks,
                )
                run_id = run.id
                if run.status in {"failed", "partial"}:
                    await _create_schedule_alert(
                        schedule,
                        claimed_at=claimed_at,
                        alert_type="schedule_run_incomplete",
                        severity="warning",
                        title=f"Scheduled checks incomplete: {schedule.name}",
                        detail=run.error_detail or f"Run finished with status {run.status}.",
                        report_id=report_record.id,
                        run_id=run.id,
                    )
            if schedule.policy_id:
                policy = await db.get(DeliverabilityPolicy, schedule.policy_id)
                if policy is not None and policy.enabled:
                    await evaluate_policy(db, policy=policy, report=report_record)
            logger.info(
                "Deliverability schedule completed: schedule=%s report=%s run=%s",
                schedule.id,
                report_record.id,
                run_id,
            )
    except Exception:
        logger.exception("Deliverability schedule failed: schedule=%s", schedule.id)
        await _create_schedule_alert(
            schedule,
            claimed_at=claimed_at,
            alert_type="schedule_failed",
            severity="error",
            title=f"Deliverability schedule failed: {schedule.name}",
            detail="The scheduled analysis failed. Review server logs and provider configuration.",
        )


async def scheduler_loop() -> None:
    next_cleanup = datetime.min.replace(tzinfo=UTC)
    while True:
        try:
            now = datetime.now(UTC)
            if now >= next_cleanup:
                reports_deleted, artifacts_deleted = await _prune_expired_data()
                if reports_deleted or artifacts_deleted:
                    logger.info(
                        "Pruned deliverability data: reports=%s artifacts=%s",
                        reports_deleted,
                        artifacts_deleted,
                    )
                next_cleanup = now + timedelta(days=1)
            claimed = await _claim_due_schedule()
            if claimed is None:
                await asyncio.sleep(30)
                continue
            await _run_schedule(*claimed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Deliverability scheduler iteration failed")
            await asyncio.sleep(30)
