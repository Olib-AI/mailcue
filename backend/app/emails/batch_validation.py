"""Batch validation, where addresses inform each other.

Validating a list one address at a time throws away the most useful evidence a
list contains. Addresses that arrive together at the same domain reveal that
domain's naming convention, and a set of generated variants of one name reveals
that the list was expanded from a pattern rather than observed. Neither signal
needs any delivery history, and neither is visible from a single address.

Grouping by domain also keeps the probe budget sane: only the first address at
a domain needs control recipients, because whether the destination accepts
everything is a property of the destination.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.emails.local_part import dominant_shape, permutation_clusters
from app.emails.mx_providers import UNKNOWN_PROVIDER
from app.emails.risk_model import BudgetCandidate, RiskAssessment, select_within_budget
from app.emails.schemas import (
    EmailValidationBatchItem,
    EmailValidationBatchResponse,
    EmailValidationBatchSummary,
    EmailValidationBudgetSelection,
    EmailValidationCatchAllRisk,
    EmailValidationRiskContribution,
)
from app.emails.validation import ValidationOutcome, validate_email_detailed, validate_syntax
from app.emails.validation_feedback import assess_catch_all_risk, record_prediction

logger = logging.getLogger("mailcue.validation.batch")

_DOMAIN_CONCURRENCY = 6
_ADDRESS_CONCURRENCY = 12

# Risk assumed for an address the probe confirmed, so a batch's blended rate
# reflects that a confirmed mailbox is not risk free but is close to it.
_CONFIRMED_RISK = 0.005
_UNDELIVERABLE_RISK = 1.0
_UNKNOWN_RISK = 0.25


@dataclass
class _AddressWork:
    email: str
    local_part: str
    domain: str
    index: int


def risk_schema(assessment: RiskAssessment) -> EmailValidationCatchAllRisk:
    """Convert a model assessment into its API representation."""
    return EmailValidationCatchAllRisk(
        score=assessment.score,
        level=assessment.level,
        recommended_action=assessment.recommended_action,
        source=assessment.source,
        sample_size=assessment.sample_size,
        explanation=assessment.explanation,
        base_rate=assessment.base_rate,
        provider_id=assessment.provider_id,
        provider_rate=assessment.provider_rate,
        confidence=assessment.confidence,
        contributions=[
            EmailValidationRiskContribution(label=item.label, delta=item.delta, detail=item.detail)
            for item in assessment.contributions
        ],
    )


def _baseline_risk(outcome: ValidationOutcome) -> float:
    response = outcome.response
    if response.deliverable is False:
        return _UNDELIVERABLE_RISK
    if response.status == "valid":
        return _CONFIRMED_RISK
    if response.status == "disposable":
        return 0.5
    return _UNKNOWN_RISK


async def validate_batch(
    db: AsyncSession,
    *,
    user_id: str,
    emails: list[str],
    target_bounce_rate: float | None = None,
    include_domain_signals: bool = True,
) -> EmailValidationBatchResponse:
    """Validate a list of addresses using batch-level and per-address evidence."""
    seen: set[str] = set()
    work: list[_AddressWork] = []
    invalid: list[EmailValidationBatchItem] = []

    for index, raw in enumerate(emails):
        candidate = (raw or "").strip()
        key = candidate.lower()
        if not candidate or key in seen:
            continue
        seen.add(key)
        syntax = validate_syntax(candidate)
        if not syntax.is_valid or not syntax.domain:
            invalid.append(
                EmailValidationBatchItem(
                    email=candidate,
                    status="invalid",
                    verdict="undeliverable",
                    deliverable=False,
                    reason="invalid_syntax",
                    risk_score=1.0,
                    recommended_action="hold",
                    error=syntax.error,
                )
            )
            continue
        work.append(
            _AddressWork(
                email=candidate,
                local_part=syntax.local_part or "",
                domain=syntax.domain,
                index=index,
            )
        )

    by_domain: dict[str, list[_AddressWork]] = {}
    for item in work:
        by_domain.setdefault(item.domain, []).append(item)

    # Batch-level evidence, computed per domain before any address is scored.
    domain_shapes: dict[str, tuple[str | None, float]] = {}
    domain_permutations: dict[str, set[str]] = {}
    for domain, members in by_domain.items():
        locals_at_domain = [member.local_part for member in members]
        domain_shapes[domain] = dominant_shape(locals_at_domain)
        domain_permutations[domain] = (
            permutation_clusters(locals_at_domain) if len(members) > 1 else set()
        )

    domain_semaphore = asyncio.Semaphore(_DOMAIN_CONCURRENCY)
    address_semaphore = asyncio.Semaphore(_ADDRESS_CONCURRENCY)
    results: dict[str, tuple[_AddressWork, ValidationOutcome]] = {}

    async def process_domain(domain: str, members: list[_AddressWork]) -> None:
        async with domain_semaphore:
            lead = members[0]
            try:
                lead_outcome = await validate_email_detailed(
                    lead.email, collect_signals=include_domain_signals
                )
            except Exception as exc:
                logger.warning("Batch validation failed for %s: %s", lead.email, exc)
                return
            results[lead.email] = (lead, lead_outcome)

            if len(members) == 1:
                return

            # The destination's accept-all behaviour is already known, so the
            # remaining addresses only need their own recipient answer.
            reuse_controls = 0 if lead_outcome.response.mailbox.catch_all is not None else None

            async def process_address(member: _AddressWork) -> None:
                async with address_semaphore:
                    try:
                        outcome = await validate_email_detailed(
                            member.email,
                            collect_signals=include_domain_signals,
                            control_probe_count=reuse_controls,
                        )
                    except Exception as exc:
                        logger.warning("Batch validation failed for %s: %s", member.email, exc)
                        return
                    if (
                        outcome.response.mailbox.catch_all is None
                        and lead_outcome.response.mailbox.catch_all is not None
                    ):
                        outcome.response.mailbox.catch_all = (
                            lead_outcome.response.mailbox.catch_all
                        )
                        if (
                            outcome.response.mailbox.catch_all
                            and outcome.response.status == "valid"
                        ):
                            outcome.response.status = "catch_all"
                            outcome.response.verdict = "risky"
                            outcome.response.deliverable = None
                            outcome.response.reason = "accept_all_domain"
                    results[member.email] = (member, outcome)

            await asyncio.gather(*(process_address(member) for member in members[1:]))

    await asyncio.gather(
        *(process_domain(domain, members) for domain, members in by_domain.items())
    )

    items: list[EmailValidationBatchItem] = list(invalid)
    for item in work:
        entry = results.get(item.email)
        if entry is None:
            items.append(
                EmailValidationBatchItem(
                    email=item.email,
                    status="undetermined",
                    verdict="unknown",
                    deliverable=None,
                    reason="validation_failed",
                    risk_score=_UNKNOWN_RISK,
                    recommended_action="caution",
                    error="Validation could not be completed for this address.",
                )
            )
            continue

        _, outcome = entry
        response = outcome.response
        provider = outcome.profile.provider if outcome.profile else UNKNOWN_PROVIDER

        shape, share = domain_shapes.get(item.domain, (None, 0.0))
        matches_pattern: bool | None = None
        if shape is not None and share >= 0.6 and len(by_domain[item.domain]) >= 3:
            matches_pattern = (
                response.local_part is not None and response.local_part.shape == shape
            )
        is_permutation = item.local_part.lower() in domain_permutations.get(item.domain, set())

        local_delta = outcome.local_part_delta
        local_notes = list(outcome.local_part_notes)
        if matches_pattern is True:
            local_delta -= 0.5
            local_notes.append("Matches the naming convention used by this domain in the batch.")
        elif matches_pattern is False:
            local_delta += 0.7
            local_notes.append("Does not match the naming convention this domain uses.")
        if is_permutation:
            local_delta += 1.0
            local_notes.append(
                "The batch contains several generated variants of this name at this domain."
            )

        risk = None
        if response.status == "catch_all":
            assessment = await assess_catch_all_risk(
                db,
                user_id=user_id,
                email=item.email,
                domain=item.domain,
                provider=provider,
                local_part_delta=local_delta,
                local_part_notes=local_notes,
                domain_signal_delta=outcome.domain_signal_delta,
                domain_signal_notes=outcome.domain_signal_notes,
                probe=outcome.probe,
            )
            risk = risk_schema(assessment)
            score = assessment.score
            action = assessment.recommended_action
        else:
            score = _baseline_risk(outcome)
            action = "send" if score <= 0.04 else "hold" if score >= 0.10 else "caution"

        await record_prediction(
            db,
            user_id=user_id,
            email=item.email,
            domain=item.domain,
            provider_id=provider.id,
            status=response.status,
            score=score,
        )

        items.append(
            EmailValidationBatchItem(
                email=item.email,
                status=response.status,
                verdict=response.verdict,
                deliverable=response.deliverable,
                reason=response.reason,
                provider_id=provider.id,
                risk_score=round(score, 4),
                recommended_action=action,
                matches_domain_pattern=matches_pattern,
                permutation_variant=is_permutation,
                catch_all_risk=risk,
            )
        )

    summary = EmailValidationBatchSummary(
        total=len(items),
        valid=sum(1 for entry in items if entry.status == "valid"),
        invalid=sum(1 for entry in items if entry.status == "invalid"),
        catch_all=sum(1 for entry in items if entry.status == "catch_all"),
        undetermined=sum(1 for entry in items if entry.status == "undetermined"),
        disposable=sum(1 for entry in items if entry.status == "disposable"),
        mean_risk_score=round(
            sum(entry.risk_score for entry in items) / len(items) if items else 0.0, 5
        ),
        projected_bounce_rate=round(
            sum(entry.risk_score for entry in items) / len(items) if items else 0.0, 5
        ),
    )

    selection = None
    if target_bounce_rate is not None:
        sendable = [entry for entry in items if entry.deliverable is not False]
        chosen = select_within_budget(
            [BudgetCandidate(email=entry.email, score=entry.risk_score) for entry in sendable],
            target_bounce_rate=target_bounce_rate,
        )
        excluded = chosen.excluded + [entry.email for entry in items if entry.deliverable is False]
        selection = EmailValidationBudgetSelection(
            target_bounce_rate=target_bounce_rate,
            projected_bounce_rate=chosen.projected_bounce_rate,
            included=chosen.included,
            excluded=excluded,
            included_count=len(chosen.included),
            excluded_count=len(excluded),
        )

    return EmailValidationBatchResponse(results=items, summary=summary, selection=selection)


def max_batch_size() -> int:
    return settings.validation_batch_max_addresses
