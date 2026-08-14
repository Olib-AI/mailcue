"""Deliverability scoring and mailbox-purpose regression tests."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from io import BytesIO
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from PIL import Image

from app.auth.models import User
from app.config import settings
from app.deliverability.models import (
    DeliverabilityArtifact,
    DeliverabilityReportRecord,
    DeliverabilityRun,
)
from app.deliverability.network import (
    _dkim_identities,
    _dkim_key_description,
    _domain_blocklist_check,
    _origin_ip,
    _spf_recursive_lookups,
)
from app.deliverability.placement import PlacementResult
from app.deliverability.providers import AnalysisFinding, AnalysisResult, PreviewResult
from app.deliverability.scheduler import _prune_expired_data
from app.deliverability.visual import RenderedArtifact, attention_estimate
from app.emails.deliverability import score_deliverability
from app.mailboxes.models import Mailbox
from app.mailboxes.schemas import MailboxCreateRequest
from app.mailboxes.service import create_mailbox
from app.warmup.models import WarmupAccount
from app.warmup.service import encrypt_password


def _raw_message(*, auth_results: str, spam_status: str | None = None) -> bytes:
    message = EmailMessage()
    message["From"] = "Sender <news@example.com>"
    message["To"] = "test@mailcue.local"
    message["Subject"] = "Your weekly product update"
    message["Date"] = "Fri, 14 Aug 2026 12:00:00 +0000"
    message["Message-ID"] = "<delivery-test@example.com>"
    message["Return-Path"] = "<bounce@example.com>"
    message["Authentication-Results"] = auth_results
    message["Received"] = (
        "from smtp.example.com (smtp.example.com [192.0.2.10]) "
        "by mx.mailcue.local with ESMTPS; Fri, 14 Aug 2026 12:00:02 +0000"
    )
    if spam_status:
        message["X-Spam-Status"] = spam_status
        message["X-Spam-Flag"] = "NO"
    message.set_content("A clear plain-text version of this useful product update.")
    message.add_alternative(
        '<html><body><h1>Product update</h1><p>Useful details.</p><img src="logo.png" alt="Example logo"></body></html>',
        subtype="html",
    )
    return message.as_bytes()


def test_strong_message_gets_actionable_high_score() -> None:
    raw = _raw_message(
        auth_results=(
            "mx.mailcue.local; spf=pass smtp.mailfrom=example.com; "
            "dkim=pass header.d=example.com header.s=mail; "
            "dmarc=pass header.from=example.com"
        ),
        spam_status="No, score=-0.8 required=5.0 tests=HTML_MESSAGE",
    )

    report = score_deliverability(raw, mailbox="test@mailcue.local", uid="7", folder="INBOX")

    assert report.score >= 90
    assert report.verdict == "excellent"
    auth = next(category for category in report.categories if category.id == "authentication")
    assert auth.score == 100
    assert {check.id: check.status for check in auth.checks} == {
        "spf": "pass",
        "dkim": "pass",
        "dmarc": "pass",
    }


def test_attention_estimate_is_a_valid_same_size_png() -> None:
    source = BytesIO()
    Image.new("RGB", (80, 40), color="white").save(source, format="PNG")

    result = attention_estimate(source.getvalue())

    assert result.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(result)) as image:
        assert image.size == (80, 40)


def test_dkim_dns_key_strength_and_revocation_are_distinguished() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    encoded = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    record = "v=DKIM1; k=rsa; p=" + base64.b64encode(encoded).decode()

    valid, weak, description = _dkim_key_description(record)

    assert valid is True
    assert weak is True
    assert "1024" in description
    assert _dkim_key_description("v=DKIM1; p=")[2].startswith("The DKIM key is revoked")
    assert _dkim_key_description("v=DKIM1; p=not-base64")[0] is False


async def test_spf_lookup_count_expands_includes_with_a_bound() -> None:
    class FakeWorker:
        async def resolve(self, name: str, record_type: str) -> list[str]:
            assert record_type == "TXT"
            return {
                "child.example.com": ["v=spf1 a mx include:leaf.example.com -all"],
                "leaf.example.com": ["v=spf1 exists:sender.example.com -all"],
            }.get(name, [])

    count, incomplete = await _spf_recursive_lookups(
        FakeWorker(),
        "v=spf1 include:child.example.com -all",
        visited={"example.com"},
    )

    assert count == 5
    assert incomplete is False


def test_origin_ip_uses_receiver_added_topmost_received_header() -> None:
    message = EmailMessage()
    message["Received"] = "from trusted.example [8.8.8.8] by mx.mailcue.local"
    message["Received"] = "from forged.example [1.1.1.1] by attacker.example"
    message.set_content("test")

    assert str(_origin_ip(message)) == "8.8.8.8"


def test_dkim_dns_identity_uses_observed_selector_and_signing_domain() -> None:
    message = EmailMessage()
    message["DKIM-Signature"] = (
        "v=1; a=rsa-sha256; d=mailer.example.com; s=transactional; bh=value; b=value"
    )
    message.set_content("test")

    assert _dkim_identities(message) == [("transactional", "mailer.example.com")]


async def test_domain_blocklists_are_explicit_and_report_the_listing_zone(
    monkeypatch: Any,
) -> None:
    class FakeWorker:
        async def resolve(self, name: str, record_type: str) -> list[str]:
            assert record_type == "A"
            return ["127.0.0.2"] if name == "link.example.com.domain-list.test" else []

    monkeypatch.setattr(
        settings, "deliverability_domain_dnsbl_zones", ["domain-list.test"]
    )
    result = await _domain_blocklist_check(
        FakeWorker(), ["sender.example.com", "link.example.com"]
    )

    assert result.status == "fail"
    assert any("link.example.com" in detail for detail in result.details)


def test_failed_authentication_and_unsafe_content_reduce_score() -> None:
    message = EmailMessage()
    message["From"] = "offers@bad.example"
    message["To"] = "test@mailcue.local"
    message["Authentication-Results"] = (
        "mx.mailcue.local; spf=fail smtp.mailfrom=other.example; "
        "dkim=none; dmarc=fail header.from=bad.example"
    )
    message.set_content(
        '<html><body><script>alert(1)</script><a href="javascript:alert(1)">ACT NOW</a>'
        "<p>BUY NOW! CLICK HERE! FREE MONEY!</p></body></html>",
        subtype="html",
    )

    report = score_deliverability(
        message.as_bytes(), mailbox="test@mailcue.local", uid="8", folder="INBOX"
    )

    assert report.score < 50
    assert report.verdict == "poor"
    failed = {
        check.id
        for category in report.categories
        for check in category.checks
        if check.status == "fail"
    }
    assert {"spf", "dmarc", "html_quality", "link_hygiene"} <= failed
    assert report.top_recommendations


def test_accessibility_checks_find_heading_contrast_and_tap_target_issues() -> None:
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "test@mailcue.local"
    message["Subject"] = "Accessible campaign"
    message.set_content("Plain alternative")
    message.add_alternative(
        '<html lang="en"><body><h1>Title</h1><h3>Skipped</h3>'
        '<a href="https://example.com" style="display:block;width:30px;height:30px;'
        'color:#777;background-color:#888">Open</a></body></html>',
        subtype="html",
    )

    report = score_deliverability(
        message.as_bytes(), mailbox="test@mailcue.local", uid="a11y", folder="INBOX"
    )
    checks = {
        check.id: check
        for category in report.categories
        for check in category.checks
    }

    assert checks["heading_order"].status == "warning"
    assert checks["inline_color_contrast"].status == "warning"
    assert checks["tap_target_size"].status == "warning"


def test_only_topmost_authentication_results_are_scored() -> None:
    raw = _raw_message(
        auth_results=(
            "mx.mailcue.local; spf=fail smtp.mailfrom=example.com; "
            "dkim=fail header.d=example.com; dmarc=fail header.from=example.com"
        )
    )
    message = EmailMessage()
    message.set_content("placeholder")
    # Add a forged passing result below the receiver's topmost result.
    split = raw.split(b"\n\n", 1)
    forged = (
        b"Authentication-Results: attacker.example; spf=pass smtp.mailfrom=example.com; "
        b"dkim=pass header.d=example.com; dmarc=pass header.from=example.com\n"
    )
    raw_with_forged = split[0] + b"\n" + forged + b"\n" + split[1]

    report = score_deliverability(
        raw_with_forged, mailbox="test@mailcue.local", uid="9", folder="INBOX"
    )
    auth = next(category for category in report.categories if category.id == "authentication")
    assert all(check.status == "fail" for check in auth.checks)


def test_malformed_message_returns_a_bounded_report() -> None:
    report = score_deliverability(
        b"Malformed header\xff\n\n\x00\xffbody",
        mailbox="test@mailcue.local",
        uid="10",
        folder="INBOX",
    )

    assert 0 <= report.score <= 100
    assert report.verdict in {"excellent", "good", "needs_work", "poor"}
    assert report.categories


async def test_mailbox_purpose_is_persisted_and_reactivation_updates_it(
    _engine_and_session: Any,
    monkeypatch: Any,
) -> None:
    _engine, factory = _engine_and_session

    async def no_provision(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr("app.mailboxes.service._provision_system_mailbox", no_provision)
    user = User(
        id="purpose-user",
        username="purpose-user",
        email="purpose-user@example.com",
        hashed_password="unused",
        is_admin=True,
        is_active=True,
    )
    async with factory() as session:
        session.add(user)
        await session.commit()
        created = await create_mailbox(
            MailboxCreateRequest(
                username="delivery-test",
                password="a-secure-password",
                purpose="deliverability",
            ),
            session,
            user_id=user.id,
        )
        assert created.purpose == "deliverability"
        created.is_active = False
        await session.commit()
        reactivated = await create_mailbox(
            MailboxCreateRequest(
                username="delivery-test",
                password="a-secure-password",
                purpose="standard",
            ),
            session,
            user_id=user.id,
        )
        assert reactivated.id == created.id
        assert reactivated.purpose == "standard"


async def test_report_endpoint_uses_owned_mailbox_and_original_bytes(
    client: AsyncClient,
    _engine_and_session: Any,
    monkeypatch: Any,
) -> None:
    _engine, factory = _engine_and_session
    async with factory() as session:
        session.add(
            Mailbox(
                address="delivery@mailcue.local",
                display_name="Delivery test",
                domain="mailcue.local",
                user_id="test-user-id",
                purpose="deliverability",
            )
        )
        await session.commit()

    raw = _raw_message(
        auth_results=(
            "mx.mailcue.local; spf=pass smtp.mailfrom=example.com; "
            "dkim=pass header.d=example.com; dmarc=pass header.from=example.com"
        )
    )

    async def fake_raw(*_args: Any, **_kwargs: Any) -> bytes:
        return raw

    monkeypatch.setattr("app.mailboxes.router.get_email_raw", fake_raw)
    response = await client.get(
        "/api/v1/mailboxes/delivery%40mailcue.local/emails/12/deliverability",
        params={"folder": "INBOX"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mailbox"] == "delivery@mailcue.local"
    assert payload["uid"] == "12"
    assert payload["score_version"] == "2.2"
    assert payload["report_id"]
    assert len(payload["raw_sha256"]) == 64
    assert payload["cached"] is False

    cached_response = await client.get(
        "/api/v1/mailboxes/delivery%40mailcue.local/emails/12/deliverability",
        params={"folder": "INBOX"},
    )
    assert cached_response.status_code == 200
    assert cached_response.json()["report_id"] == payload["report_id"]
    assert cached_response.json()["cached"] is True

    history = await client.get(
        "/api/v1/deliverability/reports",
        params={"mailbox": "delivery@mailcue.local"},
    )
    assert history.status_code == 200
    assert history.json()["total"] == 1


async def test_report_baseline_and_comparison_api(
    client: AsyncClient,
    _engine_and_session: Any,
    monkeypatch: Any,
) -> None:
    _engine, factory = _engine_and_session
    async with factory() as session:
        session.add(
            Mailbox(
                address="compare@mailcue.local",
                display_name="Comparison",
                domain="mailcue.local",
                user_id="test-user-id",
                purpose="deliverability",
            )
        )
        await session.commit()

    strong = _raw_message(
        auth_results=(
            "mx.mailcue.local; spf=pass smtp.mailfrom=example.com; "
            "dkim=pass header.d=example.com; dmarc=pass header.from=example.com"
        )
    )
    weak = EmailMessage()
    weak["From"] = "sender@other.example"
    weak["To"] = "compare@mailcue.local"
    weak["Authentication-Results"] = (
        "mx.mailcue.local; spf=fail; dkim=fail; dmarc=fail header.from=other.example"
    )
    weak.set_content("ACT NOW. BUY NOW. CLICK HERE. FREE MONEY.")

    async def fake_raw(*_args: Any, **kwargs: Any) -> bytes:
        return strong if kwargs.get("uid") == "1" else weak.as_bytes()

    monkeypatch.setattr("app.mailboxes.router.get_email_raw", fake_raw)
    base_response = await client.get(
        "/api/v1/mailboxes/compare%40mailcue.local/emails/1/deliverability"
    )
    after_response = await client.get(
        "/api/v1/mailboxes/compare%40mailcue.local/emails/2/deliverability"
    )
    assert base_response.status_code == after_response.status_code == 200
    base_id = base_response.json()["report_id"]
    after_id = after_response.json()["report_id"]

    baseline = await client.put(
        f"/api/v1/deliverability/reports/{base_id}/baseline",
        json={"is_baseline": True},
    )
    assert baseline.status_code == 200
    assert baseline.json()["is_baseline"] is True

    comparison = await client.get(f"/api/v1/deliverability/reports/{after_id}/comparison")
    assert comparison.status_code == 200
    result = comparison.json()
    assert result["before_report_id"] == base_id
    assert result["after_report_id"] == after_id
    assert result["score_delta"] < 0
    assert result["regressed"] > 0


async def test_capabilities_and_policy_evaluation_api(
    client: AsyncClient,
    _engine_and_session: Any,
    monkeypatch: Any,
) -> None:
    _engine, factory = _engine_and_session
    async with factory() as session:
        session.add(
            Mailbox(
                address="policy@mailcue.local",
                display_name="Policy test",
                domain="mailcue.local",
                user_id="test-user-id",
                purpose="deliverability",
            )
        )
        await session.commit()

    capabilities = await client.get("/api/v1/deliverability/capabilities")
    assert capabilities.status_code == 200
    by_id = {item["id"]: item for item in capabilities.json()["capabilities"]}
    assert by_id["local_analysis"]["status"] == "available"
    assert by_id["client_previews"]["status"] == "not_configured"

    weak = EmailMessage()
    weak["From"] = "sender@other.example"
    weak["To"] = "policy@mailcue.local"
    weak["Authentication-Results"] = (
        "mx.mailcue.local; spf=fail; dkim=fail; dmarc=fail header.from=other.example"
    )
    weak.set_content("ACT NOW. BUY NOW. CLICK HERE. FREE MONEY.")

    async def fake_raw(*_args: Any, **_kwargs: Any) -> bytes:
        return weak.as_bytes()

    monkeypatch.setattr("app.mailboxes.router.get_email_raw", fake_raw)
    report_response = await client.get(
        "/api/v1/mailboxes/policy%40mailcue.local/emails/1/deliverability"
    )
    assert report_response.status_code == 200
    report_id = report_response.json()["report_id"]

    policy_body = {
        "name": "Release gate",
        "mailbox": "policy@mailcue.local",
        "minimum_score": 90,
        "maximum_regression": 2,
        "fail_on_statuses": ["fail"],
        "required_check_ids": ["spf", "dkim", "dmarc"],
        "required_capabilities": ["local_analysis"],
    }
    created = await client.post("/api/v1/deliverability/policies", json=policy_body)
    assert created.status_code == 201
    policy_id = created.json()["id"]

    listed = await client.get(
        "/api/v1/deliverability/policies", params={"mailbox": "policy@mailcue.local"}
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [policy_id]

    evaluated = await client.post(
        f"/api/v1/deliverability/policies/{policy_id}/evaluate/{report_id}"
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["passed"] is False
    assert any("below the required" in reason for reason in evaluated.json()["reasons"])
    assert any("Required check 'spf'" in reason for reason in evaluated.json()["reasons"])

    alerts = await client.get("/api/v1/deliverability/alerts", params={"acknowledged": False})
    assert alerts.status_code == 200
    assert alerts.json()["total"] == 1
    alert_id = alerts.json()["alerts"][0]["id"]
    acknowledged = await client.post(f"/api/v1/deliverability/alerts/{alert_id}/acknowledge")
    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged"] is True

    deleted = await client.delete(f"/api/v1/deliverability/policies/{policy_id}")
    assert deleted.status_code == 204


async def test_schedule_crud_is_mailbox_scoped(
    client: AsyncClient,
    _engine_and_session: Any,
) -> None:
    _engine, factory = _engine_and_session
    async with factory() as session:
        session.add(
            Mailbox(
                address="scheduled@mailcue.local",
                display_name="Scheduled test",
                domain="mailcue.local",
                user_id="test-user-id",
                purpose="deliverability",
            )
        )
        await session.commit()
    body = {
        "name": "Hourly latest message",
        "mailbox": "scheduled@mailcue.local",
        "enabled": True,
        "interval_minutes": 60,
        "checks": ["dns", "reputation", "links"],
    }
    created = await client.post("/api/v1/deliverability/schedules", json=body)
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["next_run_at"] is not None

    listed = await client.get(
        "/api/v1/deliverability/schedules",
        params={"mailbox": "scheduled@mailcue.local"},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [payload["id"]]

    body["enabled"] = False
    updated = await client.put(f"/api/v1/deliverability/schedules/{payload['id']}", json=body)
    assert updated.status_code == 200
    assert updated.json()["next_run_at"] is None

    deleted = await client.delete(f"/api/v1/deliverability/schedules/{payload['id']}")
    assert deleted.status_code == 204


async def test_retention_prunes_non_baseline_data_and_preserves_baselines(
    _engine_and_session: Any,
    monkeypatch: Any,
) -> None:
    _engine, factory = _engine_and_session
    old = datetime.now(UTC) - timedelta(days=10)
    current = datetime.now(UTC)
    mailbox = Mailbox(
        id="retention-mailbox",
        address="retention@mailcue.local",
        display_name="Retention test",
        domain="mailcue.local",
        user_id="test-user-id",
        purpose="deliverability",
    )

    def report(report_id: str, *, baseline: bool, created_at: datetime) -> DeliverabilityReportRecord:
        return DeliverabilityReportRecord(
            id=report_id,
            user_id="test-user-id",
            mailbox_id=mailbox.id,
            mailbox_address=mailbox.address,
            folder="INBOX",
            uid=report_id,
            message_id=f"<{report_id}@example.com>",
            raw_sha256=(report_id[0] * 64),
            score_version="2.2",
            score=90,
            verdict="excellent",
            report_json={},
            is_baseline=baseline,
            created_at=created_at,
        )

    rows = [
        report("expired-report", baseline=False, created_at=old),
        report("current-report", baseline=False, created_at=current),
        report("baseline-report", baseline=True, created_at=old),
    ]
    runs = [
        DeliverabilityRun(
            id=f"{item.id}-run",
            user_id="test-user-id",
            mailbox_id=mailbox.id,
            report_id=item.id,
            status="completed",
            requested_checks=["visual"],
            capability_snapshot={},
            result_json={},
            created_at=item.created_at,
        )
        for item in rows
    ]
    artifacts = [
        DeliverabilityArtifact(
            id=f"{item.id}-artifact",
            user_id="test-user-id",
            run_id=f"{item.id}-run",
            kind="screenshot",
            filename=f"{item.id}.png",
            media_type="image/png",
            sha256="a" * 64,
            data=b"png",
            created_at=old,
        )
        for item in rows
    ]
    async with factory() as session:
        session.add_all([mailbox, *rows, *runs, *artifacts])
        await session.commit()

    monkeypatch.setattr("app.deliverability.scheduler.AsyncSessionLocal", factory)
    monkeypatch.setattr(settings, "deliverability_report_retention_days", 1)
    monkeypatch.setattr(settings, "deliverability_artifact_retention_days", 1)
    reports_deleted, artifacts_deleted = await _prune_expired_data()

    assert reports_deleted == 1
    assert artifacts_deleted == 2
    async with factory() as session:
        assert await session.get(DeliverabilityReportRecord, "expired-report") is None
        assert await session.get(DeliverabilityReportRecord, "current-report") is not None
        assert await session.get(DeliverabilityReportRecord, "baseline-report") is not None
        assert await session.get(DeliverabilityArtifact, "current-report-artifact") is None
        assert await session.get(DeliverabilityArtifact, "baseline-report-artifact") is not None


async def test_opt_in_network_run_is_persisted_and_truthful(
    client: AsyncClient,
    _engine_and_session: Any,
    monkeypatch: Any,
) -> None:
    _engine, factory = _engine_and_session
    async with factory() as session:
        session.add(
            Mailbox(
                address="network@mailcue.local",
                display_name="Network test",
                domain="mailcue.local",
                user_id="test-user-id",
                purpose="deliverability",
            )
        )
        await session.commit()

    raw = _raw_message(
        auth_results=(
            "mx.mailcue.local; spf=pass smtp.mailfrom=example.com; "
            "dkim=pass header.d=example.com header.s=mail; "
            "dmarc=pass header.from=example.com"
        )
    )

    async def fake_raw(*_args: Any, **_kwargs: Any) -> bytes:
        return raw

    public_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    dkim_record = "v=DKIM1; p=" + base64.b64encode(
        public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).decode()

    async def fake_resolve(_self: Any, name: str, record_type: str) -> list[str]:
        records = {
            ("example.com", "TXT"): ["v=spf1 ip4:198.51.100.1 -all"],
            ("_dmarc.example.com", "TXT"): ["v=DMARC1; p=reject; pct=100"],
            ("example.com", "MX"): ["10 mx.example.com"],
            ("mail._domainkey.example.com", "TXT"): [dkim_record],
            ("_mta-sts.example.com", "TXT"): ["v=STSv1; id=20260814"],
            ("_smtp._tls.example.com", "TXT"): ["v=TLSRPTv1; rua=mailto:tls@example.com"],
        }
        return records.get((name, record_type), [])

    monkeypatch.setattr("app.mailboxes.router.get_email_raw", fake_raw)
    monkeypatch.setattr("app.deliverability.network._DnsWorker.resolve", fake_resolve)
    monkeypatch.setattr(settings, "deliverability_network_checks_enabled", True)

    response = await client.post(
        "/api/v1/mailboxes/network%40mailcue.local/emails/1/deliverability/runs",
        json={"checks": ["dns", "reputation"]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "completed"
    assert {category["id"] for category in payload["categories"]} == {"dns", "reputation"}
    dns_checks = {
        check["id"]: check for category in payload["categories"] for check in category["checks"]
    }
    assert dns_checks["dns_spf"]["status"] == "pass"
    assert dns_checks["dns_dmarc"]["status"] == "pass"
    assert dns_checks["dns_dkim"]["status"] == "pass"

    fetched = await client.get(f"/api/v1/deliverability/runs/{payload['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == payload


async def test_provider_credentials_are_write_only_and_enable_capability(
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/api/v1/deliverability/providers",
        json={
            "name": "Preview service",
            "kind": "preview",
            "adapter": "generic_http_preview",
            "enabled": True,
            "config": {"base_url": "https://preview.example.com"},
            "secret": "provider-api-secret",
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["has_secret"] is True
    assert "secret" not in payload
    assert "ciphertext" not in payload

    listed = await client.get("/api/v1/deliverability/providers")
    assert listed.status_code == 200
    assert listed.json() == [payload]

    capabilities = await client.get("/api/v1/deliverability/capabilities")
    by_id = {item["id"]: item for item in capabilities.json()["capabilities"]}
    assert by_id["client_previews"]["status"] == "available"

    deleted = await client.delete(f"/api/v1/deliverability/providers/{payload['id']}")
    assert deleted.status_code == 204


async def test_visual_run_persists_protected_png_artifacts(
    client: AsyncClient,
    _engine_and_session: Any,
    monkeypatch: Any,
) -> None:
    _engine, factory = _engine_and_session
    async with factory() as session:
        session.add(
            Mailbox(
                address="visual@mailcue.local",
                display_name="Visual test",
                domain="mailcue.local",
                user_id="test-user-id",
                purpose="deliverability",
            )
        )
        await session.commit()
    raw = _raw_message(auth_results="mx.mailcue.local; spf=pass; dkim=pass; dmarc=pass")

    async def fake_raw(*_args: Any, **_kwargs: Any) -> bytes:
        return raw

    async def fake_render(_raw: bytes) -> list[RenderedArtifact]:
        return [
            RenderedArtifact(
                name="desktop-light",
                width=1200,
                height=900,
                data=b"\x89PNG\r\n\x1a\nrendered",
            )
        ]

    monkeypatch.setattr("app.mailboxes.router.get_email_raw", fake_raw)
    monkeypatch.setattr("app.deliverability.service.render_email", fake_render)
    monkeypatch.setattr("app.deliverability.service.chromium_executable", lambda: "/chromium")
    monkeypatch.setattr(settings, "deliverability_visual_checks_enabled", True)
    response = await client.post(
        "/api/v1/mailboxes/visual%40mailcue.local/emails/1/deliverability/runs",
        json={"checks": ["visual"]},
    )
    assert response.status_code == 200, response.text
    stored_runs = await client.get(
        f"/api/v1/deliverability/reports/{response.json()['report_id']}/runs"
    )
    assert stored_runs.status_code == 200
    assert stored_runs.json()[0]["id"] == response.json()["id"]
    evidence = response.json()["categories"][0]["checks"][0]["evidence"][0]
    artifact = await client.get(evidence["value"])
    assert artifact.status_code == 200
    assert artifact.headers["content-type"] == "image/png"
    assert artifact.content.startswith(b"\x89PNG")


async def test_byo_seed_inbox_placement_run(
    client: AsyncClient,
    _engine_and_session: Any,
    monkeypatch: Any,
) -> None:
    _engine, factory = _engine_and_session
    async with factory() as session:
        session.add_all(
            [
                Mailbox(
                    address="placement@mailcue.local",
                    display_name="Placement test",
                    domain="mailcue.local",
                    user_id="test-user-id",
                    purpose="deliverability",
                ),
                WarmupAccount(
                    id="seed-gmail",
                    name="Gmail seed",
                    email="seed@gmail.example",
                    provider="gmail",
                    smtp_host="smtp.gmail.example",
                    imap_host="imap.gmail.example",
                    username="seed@gmail.example",
                    password_encrypted=encrypt_password("secret"),
                    enabled=True,
                    verified=True,
                ),
            ]
        )
        await session.commit()

    raw = _raw_message(auth_results="mx.mailcue.local; spf=pass; dkim=pass; dmarc=pass")

    async def fake_raw(*_args: Any, **_kwargs: Any) -> bytes:
        return raw

    async def fake_classify(account: WarmupAccount, **_kwargs: Any) -> PlacementResult:
        return PlacementResult(
            account_id=account.id,
            email=account.email,
            provider=account.provider,
            placement="inbox",
            folder="INBOX",
            detail="Matched Message-ID in INBOX.",
        )

    monkeypatch.setattr("app.mailboxes.router.get_email_raw", fake_raw)
    monkeypatch.setattr("app.deliverability.service.classify_seed_account", fake_classify)
    provider = await client.post(
        "/api/v1/deliverability/providers",
        json={
            "name": "Seed inboxes",
            "kind": "placement",
            "adapter": "seed_imap",
            "config": {"account_ids": ["seed-gmail"], "folders": ["INBOX", "Spam"]},
        },
    )
    assert provider.status_code == 201, provider.text
    response = await client.post(
        "/api/v1/mailboxes/placement%40mailcue.local/emails/1/deliverability/runs",
        json={"checks": ["placement"]},
    )
    assert response.status_code == 200, response.text
    category = response.json()["categories"][0]
    assert category["id"] == "placement"
    assert category["score"] == 100
    assert category["checks"][0]["evidence"][0]["value"] == "inbox"


async def test_real_client_preview_adapter_results_are_protected(
    client: AsyncClient,
    _engine_and_session: Any,
    monkeypatch: Any,
) -> None:
    _engine, factory = _engine_and_session
    async with factory() as session:
        session.add(
            Mailbox(
                address="previews@mailcue.local",
                display_name="Preview test",
                domain="mailcue.local",
                user_id="test-user-id",
                purpose="deliverability",
            )
        )
        await session.commit()
    raw = _raw_message(auth_results="mx.mailcue.local; spf=pass; dkim=pass; dmarc=pass")

    async def fake_raw(*_args: Any, **_kwargs: Any) -> bytes:
        return raw

    async def fake_previews(*_args: Any, **_kwargs: Any) -> list[PreviewResult]:
        return [
            PreviewResult(
                client="Gmail",
                platform="Web",
                theme="dark",
                status="ready",
                description="Rendered successfully.",
                media_type="image/png",
                data=b"\x89PNG\r\n\x1a\npreview",
            )
        ]

    monkeypatch.setattr("app.mailboxes.router.get_email_raw", fake_raw)
    monkeypatch.setattr("app.deliverability.service.run_preview_provider", fake_previews)
    provider = await client.post(
        "/api/v1/deliverability/providers",
        json={
            "name": "Preview API",
            "kind": "preview",
            "adapter": "generic_http_preview",
            "config": {"base_url": "https://preview.example.com/v1/render"},
            "secret": "write-only-secret",
        },
    )
    assert provider.status_code == 201
    response = await client.post(
        "/api/v1/mailboxes/previews%40mailcue.local/emails/1/deliverability/runs",
        json={"checks": ["client_previews"]},
    )
    assert response.status_code == 200, response.text
    evidence = response.json()["categories"][0]["checks"][0]["evidence"][0]
    assert evidence["title"] == "Gmail Web dark"
    artifact = await client.get(evidence["value"])
    assert artifact.status_code == 200
    assert artifact.content.startswith(b"\x89PNG")


async def test_ai_analysis_is_explicit_advisory_and_does_not_change_base_score(
    client: AsyncClient,
    _engine_and_session: Any,
    monkeypatch: Any,
) -> None:
    _engine, factory = _engine_and_session
    async with factory() as session:
        session.add(
            Mailbox(
                address="analysis@mailcue.local",
                display_name="Analysis test",
                domain="mailcue.local",
                user_id="test-user-id",
                purpose="deliverability",
            )
        )
        await session.commit()
    raw = _raw_message(auth_results="mx.mailcue.local; spf=pass; dkim=pass; dmarc=pass")

    async def fake_raw(*_args: Any, **_kwargs: Any) -> bytes:
        return raw

    async def fake_analysis(*_args: Any, **_kwargs: Any) -> AnalysisResult:
        return AnalysisResult(
            summary="The call to action could be clearer.",
            findings=[
                AnalysisFinding(
                    severity="suggestion",
                    title="Clarify the call to action",
                    detail="The primary action is visually ambiguous.",
                    recommendation="Use one specific action label.",
                )
            ],
        )

    monkeypatch.setattr("app.mailboxes.router.get_email_raw", fake_raw)
    monkeypatch.setattr("app.deliverability.service.run_analysis_provider", fake_analysis)
    provider = await client.post(
        "/api/v1/deliverability/providers",
        json={
            "name": "Copy review",
            "kind": "analysis",
            "adapter": "generic_http_analysis",
            "config": {"base_url": "https://analysis.example.com/v1/review"},
            "secret": "write-only-secret",
        },
    )
    assert provider.status_code == 201, provider.text

    response = await client.post(
        "/api/v1/mailboxes/analysis%40mailcue.local/emails/1/deliverability/runs",
        json={"checks": ["ai_analysis"]},
    )

    assert response.status_code == 200, response.text
    category = response.json()["categories"][0]
    assert category["id"] == "ai_analysis"
    assert category["score"] is None
    assert category["max_points"] == 0
    assert category["checks"][0]["status"] == "info"
    assert category["checks"][0]["evidence"][0]["recommendation"] == (
        "Use one specific action label."
    )
