"""Forwarding rule business logic -- CRUD, matching engine, action execution."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import NotFoundError, ValidationError
from app.forwarding.models import ForwardingRule
from app.forwarding.schemas import (
    ForwardingRuleCreateRequest,
    ForwardingRuleResponse,
    ForwardingRuleUpdateRequest,
    SmtpForwardConfig,
    TestRuleRequest,
    TestRuleResponse,
    WebhookConfig,
)

logger = logging.getLogger("mailcue.forwarding")


# ── CRUD ──────────────────────────────────────────────────────────


async def list_rules(user_id: str, db: AsyncSession) -> list[ForwardingRule]:
    """Return all forwarding rules for a user, ordered by creation date."""
    stmt = (
        select(ForwardingRule)
        .where(ForwardingRule.user_id == user_id)
        .order_by(ForwardingRule.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_rule(rule_id: str, user_id: str, db: AsyncSession) -> ForwardingRule:
    """Fetch a single rule by ID, scoped to the user."""
    stmt = select(ForwardingRule).where(
        ForwardingRule.id == rule_id,
        ForwardingRule.user_id == user_id,
    )
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if rule is None:
        raise NotFoundError("ForwardingRule", rule_id)
    return rule


async def create_rule(
    body: ForwardingRuleCreateRequest,
    user_id: str,
    db: AsyncSession,
) -> ForwardingRule:
    """Create a new forwarding rule."""
    rule = ForwardingRule(
        user_id=user_id,
        name=body.name,
        enabled=body.enabled,
        match_from=body.match_from,
        match_to=body.match_to,
        match_subject=body.match_subject,
        match_mailbox=body.match_mailbox,
        action_type=body.action_type,
        action_config=json.dumps(body.action_config),
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    logger.info("Forwarding rule '%s' created (id=%s).", rule.name, rule.id)
    return rule


async def update_rule(
    rule_id: str,
    body: ForwardingRuleUpdateRequest,
    user_id: str,
    db: AsyncSession,
) -> ForwardingRule:
    """Update an existing forwarding rule (partial update)."""
    rule = await get_rule(rule_id, user_id, db)

    # When action_type changes, action_config must also be provided so we can
    # validate the pair.  When only action_config changes, we validate against
    # the existing action_type.
    effective_action_type = body.action_type if body.action_type is not None else rule.action_type
    if body.action_config is not None:
        if effective_action_type == "smtp_forward":
            SmtpForwardConfig(**body.action_config)
        elif effective_action_type == "webhook":
            WebhookConfig(**body.action_config)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "action_config" and value is not None:
            setattr(rule, field, json.dumps(value))
        else:
            setattr(rule, field, value)

    rule.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(rule)
    logger.info("Forwarding rule '%s' updated (id=%s).", rule.name, rule.id)
    return rule


async def delete_rule(rule_id: str, user_id: str, db: AsyncSession) -> None:
    """Delete a forwarding rule permanently."""
    rule = await get_rule(rule_id, user_id, db)
    await db.delete(rule)
    await db.commit()
    logger.info("Forwarding rule '%s' deleted (id=%s).", rule.name, rule.id)


# ── Matching engine ──────────────────────────────────────────────


def _matches_pattern(pattern: str | None, value: str) -> bool:
    """Test whether a regex pattern matches the given value.

    Returns ``True`` when:
    - The pattern is ``None`` or empty (wildcard/match-all).
    - The pattern matches anywhere in *value* (``re.search`` semantics).
    """
    if not pattern:
        return True
    try:
        return re.search(pattern, value, re.IGNORECASE) is not None
    except re.error:
        logger.warning("Invalid regex in forwarding rule pattern: %s", pattern)
        return False


def evaluate_rule(
    rule: ForwardingRule,
    *,
    from_address: str,
    to_address: str,
    subject: str,
    mailbox: str,
) -> dict[str, bool]:
    """Evaluate a single rule against email metadata.

    Returns a dict with per-field match results, e.g.
    ``{"match_from": True, "match_to": True, ...}``.
    """
    return {
        "match_from": _matches_pattern(rule.match_from, from_address),
        "match_to": _matches_pattern(rule.match_to, to_address),
        "match_subject": _matches_pattern(rule.match_subject, subject),
        "match_mailbox": _matches_pattern(rule.match_mailbox, mailbox)
        if rule.match_mailbox
        else True,
    }


def rule_matches(
    rule: ForwardingRule,
    *,
    from_address: str,
    to_address: str,
    subject: str,
    mailbox: str,
) -> bool:
    """Return ``True`` when all non-empty patterns in the rule match."""
    details = evaluate_rule(
        rule,
        from_address=from_address,
        to_address=to_address,
        subject=subject,
        mailbox=mailbox,
    )
    return all(details.values())


async def test_rule(
    rule_id: str,
    user_id: str,
    sample: TestRuleRequest,
    db: AsyncSession,
) -> TestRuleResponse:
    """Dry-run a rule against sample email data without executing the action."""
    rule = await get_rule(rule_id, user_id, db)
    details = evaluate_rule(
        rule,
        from_address=sample.from_address,
        to_address=sample.to_address,
        subject=sample.subject,
        mailbox=sample.mailbox,
    )
    return TestRuleResponse(
        matched=all(details.values()),
        rule_id=rule.id,
        rule_name=rule.name,
        match_details=details,
    )


# ── Action execution ─────────────────────────────────────────────


async def _execute_smtp_forward(
    config: SmtpForwardConfig,
    email_data: dict[str, Any],
) -> None:
    """Forward the email via SMTP relay to the configured address."""
    import email.utils
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    import aiosmtplib

    msg = MIMEMultipart("alternative")
    msg["From"] = email_data.get("from", f"forwarding@{settings.domain}")
    msg["To"] = config.to_address
    msg["Subject"] = f"[Fwd] {email_data.get('subject', '(no subject)')}"
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=settings.domain)
    msg["X-Mailer"] = "MailCue/1.0 (Forwarding)"
    msg["X-Forwarded-For"] = email_data.get("to", "")

    body = email_data.get("subject", "Forwarded email from MailCue")
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            recipients=[config.to_address],
            start_tls=False,
            use_tls=False,
        )
        logger.info("Forwarded email to %s via SMTP.", config.to_address)
    except Exception as exc:
        logger.error("SMTP forward to %s failed: %s", config.to_address, exc)
        raise


async def _execute_webhook(
    config: WebhookConfig,
    email_data: dict[str, Any],
) -> None:
    """POST the email data as JSON to the configured webhook URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=config.method,
                url=config.url,
                json=email_data,
                headers=config.headers,
            )
            logger.info(
                "Webhook delivered to %s (status=%d).",
                config.url,
                response.status_code,
            )
        except httpx.HTTPError as exc:
            logger.error("Webhook delivery to %s failed: %s", config.url, exc)
            raise


async def execute_rule_action(
    rule: ForwardingRule,
    email_data: dict[str, Any],
) -> None:
    """Execute the configured action for a matched rule."""
    config_dict: dict[str, Any] = json.loads(rule.action_config)

    if rule.action_type == "smtp_forward":
        config = SmtpForwardConfig(**config_dict)
        await _execute_smtp_forward(config, email_data)
    elif rule.action_type == "webhook":
        config = WebhookConfig(**config_dict)
        await _execute_webhook(config, email_data)
    else:
        raise ValidationError(f"Unknown action type: {rule.action_type}")


# ── Auto-trigger: evaluate all rules for an incoming email ───────


async def process_incoming_email(
    db: AsyncSession,
    *,
    from_address: str,
    to_address: str,
    subject: str,
    mailbox: str,
    uid: str,
) -> int:
    """Evaluate all enabled forwarding rules against an incoming email.

    Executes matching actions and returns the number of rules that fired.
    Errors in individual rule actions are logged but do not abort processing
    of remaining rules.
    """
    stmt = select(ForwardingRule).where(ForwardingRule.enabled.is_(True))
    result = await db.execute(stmt)
    rules = list(result.scalars().all())

    # Check if any rules match before fetching the full email content
    matching_rules = [
        rule
        for rule in rules
        if rule_matches(
            rule,
            from_address=from_address,
            to_address=to_address,
            subject=subject,
            mailbox=mailbox,
        )
    ]

    if not matching_rules:
        return 0

    # Fetch the full email content for the payload
    email_data: dict[str, Any] = {
        "from": from_address,
        "to": to_address,
        "subject": subject,
        "mailbox": mailbox,
        "uid": uid,
    }
    try:
        from app.emails.service import get_email

        detail = await get_email(mailbox, uid)
        email_data.update(
            {
                "to_addresses": detail.to_addresses,
                "cc_addresses": detail.cc_addresses,
                "date": detail.date if isinstance(detail.date, str) else str(detail.date),
                "message_id": detail.message_id,
                "text_body": detail.text_body,
                "html_body": detail.html_body,
                "has_attachments": detail.has_attachments,
                "is_read": detail.is_read,
                "headers": detail.raw_headers,
            }
        )
    except Exception:
        logger.warning(
            "Could not fetch full email content for uid=%s in %s, forwarding metadata only.",
            uid,
            mailbox,
        )

    fired = 0
    for rule in matching_rules:
        try:
            await execute_rule_action(rule, email_data)
            fired += 1
            logger.info(
                "Forwarding rule '%s' (id=%s) fired for email uid=%s.",
                rule.name,
                rule.id,
                uid,
            )
        except Exception:
            logger.exception(
                "Forwarding rule '%s' (id=%s) action failed for email uid=%s.",
                rule.name,
                rule.id,
                uid,
            )

    if fired > 0:
        logger.info("%d forwarding rule(s) fired for email uid=%s in %s.", fired, uid, mailbox)
    return fired


def rule_to_response(rule: ForwardingRule) -> ForwardingRuleResponse:
    """Convert a ForwardingRule ORM instance to a Pydantic response."""
    config_dict: dict[str, Any] = json.loads(rule.action_config) if rule.action_config else {}
    return ForwardingRuleResponse(
        id=rule.id,
        name=rule.name,
        enabled=rule.enabled,
        match_from=rule.match_from,
        match_to=rule.match_to,
        match_subject=rule.match_subject,
        match_mailbox=rule.match_mailbox,
        action_type=rule.action_type,
        action_config=config_dict,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )
