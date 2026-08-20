"""Scheduler that advances staged sends through their observation window."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.emails.canary import decide, dispatch_sample, score_and_assign_sample
from app.emails.models import EmailSendCanary

logger = logging.getLogger("mailcue.canary.scheduler")

_TICK_SECONDS = 30.0
_BATCH_LIMIT = 20


async def _dispatch_pending() -> int:
    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(EmailSendCanary)
                    .where(EmailSendCanary.status == "pending")
                    .order_by(EmailSendCanary.created_at)
                    .limit(_BATCH_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        dispatched = 0
        for canary in rows:
            try:
                # Scoring probes every recipient, so it happens here rather
                # than in the request that created the batch.
                if await score_and_assign_sample(db, canary) == 0:
                    continue
                await dispatch_sample(db, canary)
                dispatched += 1
            except Exception:
                logger.exception("Failed to dispatch staged send sample: id=%s", canary.id)
        return dispatched


async def _decide_due() -> int:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(EmailSendCanary)
                    .where(
                        EmailSendCanary.status == "probing",
                        EmailSendCanary.decision_due_at.is_not(None),
                        EmailSendCanary.decision_due_at <= now,
                    )
                    .order_by(EmailSendCanary.decision_due_at)
                    .limit(_BATCH_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        decided = 0
        for canary in rows:
            if not canary.auto_release:
                # The caller wants to make the call themselves; the window has
                # closed but the batch stays put until they act on it.
                continue
            try:
                await decide(db, canary)
                decided += 1
            except Exception:
                logger.exception("Failed to decide staged send: id=%s", canary.id)
        return decided


async def scheduler_loop() -> None:
    """Dispatch sample waves and resolve staged sends whose hold window elapsed."""
    if not settings.canary_enabled:
        logger.info("Staged sending disabled; scheduler not started")
        return
    logger.info("Staged send scheduler started (tick=%.0fs)", _TICK_SECONDS)
    while True:
        try:
            await _dispatch_pending()
            await _decide_due()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Staged send scheduler tick failed")
        await asyncio.sleep(_TICK_SECONDS)
