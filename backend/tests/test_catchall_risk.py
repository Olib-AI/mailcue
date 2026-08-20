"""Tests for provider-aware rejection handling and accept-all risk scoring."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.emails.canary import (
    choose_sample,
    create_canary,
    decide,
    dispatch_sample,
    score_and_assign_sample,
)
from app.emails.dsn import parse_dsn
from app.emails.local_part import analyze_local_part, dominant_shape, permutation_clusters
from app.emails.models import EmailSendCanary, EmailSendCanaryRecipient
from app.emails.mx_providers import classify_mx, parse_mx_hosts
from app.emails.risk_model import (
    BudgetCandidate,
    ObservationCounts,
    ProbeEvidence,
    calibration_report,
    compute_risk,
    select_within_budget,
)
from app.emails.schemas import (
    CreateSendCanaryRequest,
    EmailValidationBatchItem,
    EmailValidationBatchResponse,
    EmailValidationBatchSummary,
)
from app.emails.smtp_reply import classify_rcpt_response, extract_enhanced_status
from app.emails.validation import build_control_locals

MICROSOFT = classify_mx(["acme-com.mail.protection.outlook.com"], "acme.com").provider
GOOGLE = classify_mx(["aspmx.l.google.com"], "acme.com").provider
PROOFPOINT = classify_mx(["mx1.pphosted.com"], "acme.com").provider


def _batch_response(emails: list[str], *, risk: float) -> EmailValidationBatchResponse:
    items = [
        EmailValidationBatchItem(
            email=email,
            status="catch_all",
            verdict="risky",
            deliverable=None,
            reason="accept_all_domain",
            risk_score=risk,
            recommended_action="send" if risk <= 0.04 else "caution",
        )
        for email in emails
    ]
    return EmailValidationBatchResponse(
        results=items,
        summary=EmailValidationBatchSummary(
            total=len(items),
            valid=0,
            invalid=0,
            catch_all=len(items),
            undetermined=0,
            disposable=0,
            mean_risk_score=risk,
            projected_bounce_rate=risk,
        ),
    )


async def _recipients(session: AsyncSession, canary_id: str) -> list[EmailSendCanaryRecipient]:
    result = await session.execute(
        select(EmailSendCanaryRecipient)
        .where(EmailSendCanaryRecipient.canary_id == canary_id)
        .order_by(EmailSendCanaryRecipient.email)
    )
    return list(result.scalars().all())


def _add_recipient(
    session: AsyncSession,
    canary_id: str,
    email: str,
    role: str,
    status: str,
    risk_score: float,
) -> None:
    session.add(
        EmailSendCanaryRecipient(
            canary_id=canary_id,
            email=email,
            email_hash=email,
            domain=email.rsplit("@", 1)[-1],
            role=role,
            status=status,
            risk_score=risk_score,
        )
    )


async def _dispatch(session: AsyncSession, canary: EmailSendCanary) -> int:
    with patch("app.emails.service.send_email", new=AsyncMock(return_value="mid")):
        return await dispatch_sample(session, canary)


# ── Provider classification ──────────────────────────────────────


def test_gateway_wins_over_the_mailbox_host_behind_it() -> None:
    # The gateway is what answers RCPT, so it decides whether an accept-all
    # response carries any recipient information.
    profile = classify_mx(["mx1.pphosted.com", "acme-com.mail.protection.outlook.com"], "acme.com")
    assert profile.provider.id == "proofpoint"
    assert profile.provider.fronts_backend is True


def test_self_hosted_mx_inside_the_recipient_domain_is_recognised() -> None:
    assert classify_mx(["mail.acme.com"], "acme.com").provider.id == "self_hosted"


def test_consumer_and_workspace_google_are_distinguished() -> None:
    assert classify_mx(["gmail-smtp-in.l.google.com"], "gmail.com").provider.id == "gmail_consumer"
    assert classify_mx(["aspmx.l.google.com"], "acme.com").provider.id == "google_workspace"


def test_absent_mx_is_unroutable() -> None:
    assert classify_mx([], "acme.com").provider.id == "no_mx"


def test_mx_hosts_are_parsed_from_the_dns_stage_format() -> None:
    assert parse_mx_hosts(["10 mx1.example.com.", "20 mx2.example.com."]) == [
        "mx1.example.com",
        "mx2.example.com",
    ]


# ── RCPT reply classification ────────────────────────────────────


def test_universal_absent_codes_are_definitive() -> None:
    for message in (
        "5.1.1 The email account that you tried to reach does not exist",
        "5.1.10 RESOLVER.ADR.RecipientNotFound; Recipient not found",
        "5.2.1 mailbox disabled",
    ):
        assert classify_rcpt_response(550, message).is_absent, message


def test_directory_edge_blocking_is_definitive_only_at_microsoft() -> None:
    # 5.4.1 is how Microsoft reports an unknown recipient and how most other
    # receivers report an unexplained policy refusal.
    message = "5.4.1 Recipient address rejected: Access denied"
    assert classify_rcpt_response(550, message, MICROSOFT).is_absent
    assert classify_rcpt_response(550, message).verdict == "policy"
    assert classify_rcpt_response(550, message, GOOGLE).verdict == "policy"


def test_an_accurate_phrase_outranks_an_inaccurate_class() -> None:
    result = classify_rcpt_response(550, "5.7.1 delivery refused, user unknown")
    assert result.is_absent


def test_sender_refusals_are_never_recipient_evidence() -> None:
    result = classify_rcpt_response(
        550, "5.7.1 Service unavailable, client host blocked using Spamhaus"
    )
    assert result.verdict == "policy"
    assert result.reason_code == "sender_blocked"
    assert result.sender_reputation_signal is True


def test_temporary_and_accepted_replies_map_cleanly() -> None:
    assert classify_rcpt_response(451, "4.7.1 greylisted").verdict == "temporary"
    assert classify_rcpt_response(250, "2.1.5 Recipient OK").is_present


def test_enhanced_status_extraction() -> None:
    assert extract_enhanced_status("550 5.1.1 no such user") == "5.1.1"
    assert extract_enhanced_status("550 no such user") is None


# ── Control recipient generation ─────────────────────────────────


def test_controls_span_several_shapes_and_avoid_the_target() -> None:
    controls = build_control_locals("john.smith", 3)
    assert len(controls) == 3
    assert "john.smith" not in controls
    # A plausible name, a shape-matched variant, and a high-entropy string.
    assert any("." in value and value[-4:].isdigit() for value in controls)
    assert any(len(value) >= 16 and value.isalnum() for value in controls)


def test_shape_matched_control_mirrors_the_target_layout() -> None:
    controls = build_control_locals("first.last", 3)
    shaped = [value for value in controls if value.count(".") == 1 and not value[-1].isdigit()]
    assert shaped, controls
    left, right = shaped[0].split(".")
    assert (len(left), len(right)) == (5, 4)


def test_short_local_parts_get_a_collision_resistant_control() -> None:
    # A two-letter random control would plausibly hit a real mailbox, which
    # would look like an accept-all.
    controls = build_control_locals("jo", 3)
    shaped = [value for value in controls if value.isalpha()]
    assert all(len(value) >= 6 for value in shaped), controls


# ── Local-part signals ───────────────────────────────────────────


def test_role_accounts_lower_risk_and_gibberish_raises_it() -> None:
    role = analyze_local_part("support")
    assert role.is_role_account and role.risk_delta < 0
    noise = analyze_local_part("7f3a91b2c8d4e6a0")
    assert noise.gibberish_score > 0.5 and noise.risk_delta > 1


def test_placeholders_are_flagged() -> None:
    assert analyze_local_part("yourname").is_placeholder is True
    assert analyze_local_part("sarah.chen").is_placeholder is False


def test_conventional_names_are_not_penalised() -> None:
    assert analyze_local_part("sarah.chen").risk_delta < 0


def test_dominant_shape_reflects_the_batch_convention() -> None:
    shape, share = dominant_shape(["a.b", "c.d", "e.f", "ghi"])
    assert shape == "dotted"
    assert share == 0.75


def test_generated_name_variants_are_clustered() -> None:
    # Only one of these can be the live mailbox.
    flagged = permutation_clusters(["j.smith", "jsmith", "john.smith", "amara.okonkwo"])
    assert "j.smith" in flagged
    assert "amara.okonkwo" not in flagged


# ── Risk model ───────────────────────────────────────────────────


def test_provider_prior_applies_with_no_history_at_all() -> None:
    gateway = compute_risk(provider=PROOFPOINT)
    workspace = compute_risk(provider=GOOGLE)
    assert gateway.source == "provider_prior"
    # A gateway that may not know the recipient directory is a much worse bet
    # than a provider that answers RCPT honestly.
    assert gateway.score > workspace.score * 2


def test_domain_outcomes_pull_the_estimate_off_the_provider_prior() -> None:
    clean = compute_risk(
        provider=PROOFPOINT,
        domain_counts=ObservationCounts(delivered=60, hard_bounce=0),
    )
    dirty = compute_risk(
        provider=PROOFPOINT,
        domain_counts=ObservationCounts(delivered=10, hard_bounce=40),
    )
    assert clean.score < PROOFPOINT.accept_all_bounce_prior < dirty.score
    assert clean.source == "domain_history"


def test_shared_domain_history_is_labelled_distinctly() -> None:
    result = compute_risk(
        provider=GOOGLE,
        domain_counts=ObservationCounts(delivered=30, hard_bounce=1, tenants=4),
        domain_counts_shared=True,
    )
    assert result.source == "shared_domain_history"


def test_a_selective_destination_lowers_risk_sharply() -> None:
    base = compute_risk(provider=PROOFPOINT)
    selective = compute_risk(
        provider=PROOFPOINT,
        probe=ProbeEvidence(
            accepted=True, control_total=3, control_accepted=0, control_rejected=3
        ),
    )
    assert selective.score < base.score
    assert any(item.label == "probe_selective" for item in selective.contributions)


def test_a_reputation_signal_pulls_the_estimate_back_to_the_prior() -> None:
    # The destination was reacting to the probing host, so its answers say
    # nothing about the mailbox and the score must not pretend otherwise.
    confident = compute_risk(
        provider=GOOGLE,
        domain_counts=ObservationCounts(delivered=80, hard_bounce=0),
    )
    muddied = compute_risk(
        provider=GOOGLE,
        domain_counts=ObservationCounts(delivered=80, hard_bounce=0),
        probe=ProbeEvidence(
            accepted=True,
            control_total=3,
            control_accepted=3,
            sender_reputation_signal=True,
        ),
    )
    assert muddied.score > confident.score
    assert muddied.confidence <= 0.35


def test_local_part_and_domain_signals_shift_the_score() -> None:
    plain = compute_risk(provider=GOOGLE)
    risky = compute_risk(provider=GOOGLE, local_part_delta=2.2, domain_signal_delta=1.4)
    assert risky.score > plain.score
    labels = {item.label for item in risky.contributions}
    assert {"local_part", "domain_signals"} <= labels


# ── Budget selection ─────────────────────────────────────────────


def test_budget_selection_takes_the_largest_set_under_the_ceiling() -> None:
    candidates = [
        BudgetCandidate("a@x.com", 0.005),
        BudgetCandidate("b@x.com", 0.005),
        BudgetCandidate("c@x.com", 0.30),
        BudgetCandidate("d@x.com", 0.02),
    ]
    result = select_within_budget(candidates, target_bounce_rate=0.02)
    assert set(result.included) == {"a@x.com", "b@x.com", "d@x.com"}
    assert result.excluded == ["c@x.com"]
    assert result.projected_bounce_rate <= 0.02


def test_committed_addresses_create_headroom_for_a_risky_one() -> None:
    # Ten confirmed addresses at 0.5% leave room for one address at 12% while
    # the blended rate stays under the 2% ceiling.
    result = select_within_budget(
        [BudgetCandidate("risky@x.com", 0.12)],
        target_bounce_rate=0.02,
        committed=[0.005] * 10,
    )
    assert result.included == ["risky@x.com"]
    assert result.projected_bounce_rate <= 0.02


def test_a_risky_address_is_excluded_without_enough_headroom() -> None:
    result = select_within_budget(
        [BudgetCandidate("risky@x.com", 0.12)],
        target_bounce_rate=0.02,
        committed=[0.005] * 2,
    )
    assert result.included == []
    assert result.excluded == ["risky@x.com"]


# ── Calibration ──────────────────────────────────────────────────


def test_calibration_reports_brier_score_and_bins() -> None:
    observations = [(0.05, False)] * 19 + [(0.05, True)]
    report = calibration_report(observations)
    assert report.sample_size == 20
    assert report.observed_rate == 0.05
    assert report.brier_score is not None
    assert report.bins[0].predicted_mean == 0.05


def test_calibration_of_an_empty_history_is_empty() -> None:
    report = calibration_report([])
    assert report.sample_size == 0
    assert report.brier_score is None


# ── Canary sampling ──────────────────────────────────────────────


def test_canary_sample_always_includes_the_riskiest_address() -> None:
    scored = [(f"{index}@x.com", index / 10) for index in range(10)]
    sample, held = choose_sample(scored, 3)
    assert "9@x.com" in sample
    assert len(sample) == 3
    assert len(held) == 7
    assert not set(sample) & set(held)


def test_canary_sample_spans_the_risk_range() -> None:
    # A sample drawn only from the safe end would clear a batch the risky end
    # would have failed.
    scored = [(f"{index}@x.com", index / 100) for index in range(100)]
    sample, _held = choose_sample(scored, 3)
    scores = sorted(dict(scored)[email] for email in sample)
    assert scores[0] < 0.1
    assert scores[-1] > 0.9


def test_canary_sample_smaller_than_the_batch_holds_nothing_back() -> None:
    sample, held = choose_sample([("only@x.com", 0.1)], 3)
    assert sample == ["only@x.com"]
    assert held == []


# ── DSN parsing ──────────────────────────────────────────────────

_HARD_BOUNCE = """From: MAILER-DAEMON@mx.example.net
To: sender@mailcue.io
Subject: Undelivered Mail Returned to Sender
Content-Type: multipart/report; report-type=delivery-status; boundary="XYZ"

--XYZ
Content-Type: text/plain

This is the mail system at host mx.example.net.

--XYZ
Content-Type: message/delivery-status

Reporting-MTA: dns; mx.example.net

Final-Recipient: rfc822; nobody@acme.com
Original-Recipient: rfc822;nobody@acme.com
Action: failed
Status: 5.1.1
Diagnostic-Code: smtp; 550 5.1.1 <nobody@acme.com>: Recipient address rejected: User unknown

--XYZ
Content-Type: text/rfc822-headers

Message-ID: <original@mailcue.io>

--XYZ--
"""

_SOFT_BOUNCE = _HARD_BOUNCE.replace("Action: failed", "Action: delayed").replace(
    "Status: 5.1.1", "Status: 4.2.2"
)


def test_hard_bounce_dsn_is_parsed_into_a_recipient_outcome() -> None:
    report = parse_dsn(_HARD_BOUNCE)
    assert report.is_dsn is True
    assert report.reporting_mta == "mx.example.net"
    assert report.original_message_id == "<original@mailcue.io>"
    assert len(report.recipients) == 1
    entry = report.recipients[0]
    assert entry.recipient == "nobody@acme.com"
    assert entry.outcome == "hard_bounce"
    assert entry.status == "5.1.1"
    assert entry.smtp_code == 550


def test_delayed_notifications_are_soft_bounces() -> None:
    report = parse_dsn(_SOFT_BOUNCE)
    assert report.recipients[0].outcome == "soft_bounce"


def test_ordinary_mail_is_not_treated_as_a_notification() -> None:
    ordinary = (
        "From: colleague@example.com\r\n"
        "To: me@mailcue.io\r\n"
        "Subject: lunch\r\n\r\n"
        "See you at one.\r\n"
    )
    assert parse_dsn(ordinary).is_dsn is False


def test_non_conforming_bounces_fall_back_to_the_heuristic() -> None:
    legacy = (
        "From: Mail Delivery Subsystem <MAILER-DAEMON@mx.example.net>\r\n"
        "To: sender@mailcue.io\r\n"
        "Subject: Returned mail: see transcript for details\r\n"
        "Content-Type: text/plain\r\n\r\n"
        "Your message could not be delivered.\r\n"
        "   ----- The following addresses had permanent fatal errors -----\r\n"
        "<ghost@acme.com>\r\n"
        "550 5.1.1 User unknown\r\n"
    )
    report = parse_dsn(legacy)
    assert report.is_dsn is True
    assert [entry.recipient for entry in report.recipients] == ["ghost@acme.com"]
    assert report.recipients[0].outcome == "hard_bounce"


def test_the_reporting_host_is_not_mistaken_for_a_recipient() -> None:
    legacy = (
        "From: MAILER-DAEMON@mx.example.net\r\n"
        "To: sender@mailcue.io\r\n"
        "Subject: Delivery has failed\r\n"
        "Content-Type: text/plain\r\n\r\n"
        "Reported by <postmaster@mx.example.net> for <ghost@acme.com>: "
        "550 5.1.1 user unknown\r\n"
    )
    recipients = [entry.recipient for entry in parse_dsn(legacy).recipients]
    assert recipients == ["ghost@acme.com"]


# ── Staged send lifecycle ────────────────────────────────────────


@pytest.mark.asyncio
async def test_staged_send_scores_then_releases_on_a_clean_sample(
    _engine_and_session: Any,
) -> None:
    """A staged send scores in the scheduler, not in the request that made it."""
    _engine, factory = _engine_and_session
    async with factory() as session:
        session.add(
            User(
                id="canary-user",
                username="canary",
                email="canary@mailcue.local",
                hashed_password="unused",
                is_admin=True,
                is_active=True,
            )
        )
        await session.commit()

    request = CreateSendCanaryRequest(
        recipients=[f"person{index}@acme-corp.com" for index in range(6)],
        from_address="hello@mailcue.local",
        subject="Quarterly update",
        body="hello",
        sample_size=2,
        hold_minutes=5,
    )

    async with factory() as session:
        canary = await create_canary(session, user_id="canary-user", request=request)
        assert canary.status == "pending"
        # Nothing is scored or sampled yet: the request returns before any
        # recipient has been probed.
        rows = await _recipients(session, canary.id)
        assert all(row.role == "held" and row.risk_score is None for row in rows)

        scored_batch = _batch_response(request.recipients, risk=0.02)
        with patch(
            "app.emails.batch_validation.validate_batch",
            new=AsyncMock(return_value=scored_batch),
        ):
            sendable = await score_and_assign_sample(session, canary)
        assert sendable == 6

        rows = await _recipients(session, canary.id)
        assert sum(1 for row in rows if row.role == "sample") == 2
        assert all(row.risk_score == 0.02 for row in rows)

        sent = await _dispatch(session, canary)
        assert sent == 2
        assert canary.status == "probing"

        with patch("app.emails.service.send_email", new=AsyncMock(return_value="mid")):
            await decide(session, canary)
        assert canary.status == "released"
        rows = await _recipients(session, canary.id)
        assert sum(1 for row in rows if row.status == "released") == 4


@pytest.mark.asyncio
async def test_a_partly_failed_sample_releases_only_the_safer_addresses(
    _engine_and_session: Any,
) -> None:
    _engine, factory = _engine_and_session
    async with factory() as session:
        session.add(
            User(
                id="canary-user-2",
                username="canary2",
                email="canary2@mailcue.local",
                hashed_password="unused",
                is_admin=True,
                is_active=True,
            )
        )
        await session.commit()

    async with factory() as session:
        canary = EmailSendCanary(
            user_id="canary-user-2",
            status="probing",
            sample_size=2,
            hold_minutes=5,
            from_address="hello@mailcue.local",
            subject="x",
            body="y",
        )
        session.add(canary)
        await session.flush()
        # The risky sample bounced; the safe one delivered. The destination
        # does evaluate recipients, so the per-address scores mean something.
        _add_recipient(session, canary.id, "risky@acme-corp.com", "sample", "hard_bounce", 0.60)
        _add_recipient(session, canary.id, "safe@acme-corp.com", "sample", "sent", 0.03)
        _add_recipient(session, canary.id, "below@acme-corp.com", "held", "pending", 0.05)
        _add_recipient(session, canary.id, "above@acme-corp.com", "held", "pending", 0.80)
        await session.commit()

        with patch("app.emails.service.send_email", new=AsyncMock(return_value="mid")):
            await decide(session, canary)

        assert canary.status == "released"
        by_email = {row.email: row for row in await _recipients(session, canary.id)}
        assert by_email["below@acme-corp.com"].status == "released"
        assert by_email["above@acme-corp.com"].status == "blocked"


@pytest.mark.asyncio
async def test_a_wholly_failed_sample_blocks_the_remainder(
    _engine_and_session: Any,
) -> None:
    _engine, factory = _engine_and_session
    async with factory() as session:
        session.add(
            User(
                id="canary-user-3",
                username="canary3",
                email="canary3@mailcue.local",
                hashed_password="unused",
                is_admin=True,
                is_active=True,
            )
        )
        await session.commit()

    async with factory() as session:
        canary = EmailSendCanary(
            user_id="canary-user-3",
            status="probing",
            sample_size=2,
            hold_minutes=5,
            from_address="hello@mailcue.local",
            subject="x",
            body="y",
        )
        session.add(canary)
        await session.flush()
        _add_recipient(session, canary.id, "a@dead-domain.com", "sample", "hard_bounce", 0.4)
        _add_recipient(session, canary.id, "b@dead-domain.com", "sample", "hard_bounce", 0.1)
        _add_recipient(session, canary.id, "c@dead-domain.com", "held", "pending", 0.01)
        await session.commit()

        await decide(session, canary)

        assert canary.status == "blocked"
        by_email = {row.email: row for row in await _recipients(session, canary.id)}
        # Even the safest held address stays put once the whole sample failed.
        assert by_email["c@dead-domain.com"].status == "blocked"


# ── Route resolution ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_literal_validation_paths_are_not_shadowed_by_the_uid_route(
    client: AsyncClient,
) -> None:
    """GET /emails/{uid} matches any single segment, including literal names.

    These paths were unreachable in production because they were registered
    after the path-parameter route, so every request resolved to "fetch the
    email whose uid is 'suppressed-domains'" and came back demanding a
    mailbox query parameter.

    Asserted through real requests rather than by inspecting app.routes:
    FastAPI stopped flattening included routers into that list, so structural
    checks pass or fail on the installed version rather than on the routing.
    """
    for path in (
        "/api/v1/emails/validation-calibration",
        "/api/v1/emails/suppressed-domains",
        "/api/v1/emails/send-canaries",
    ):
        response = await client.get(path)
        assert response.status_code == 200, (
            f"{path} returned {response.status_code}: {response.text[:200]}"
        )

    # The parameterised route still works for an actual uid.
    shadowed = await client.get("/api/v1/emails/some-uid")
    assert shadowed.status_code == 422
    assert "mailbox" in shadowed.text
