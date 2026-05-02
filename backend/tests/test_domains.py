"""End-to-end tests for the domains module — DNS verify + drift detection.

Covers:
  - ``POST /verify-dns`` advances both ``*_last_checked_at`` and
    ``*_last_verified_at`` when every record resolves correctly.
  - On drift, ``*_last_checked_at`` advances but ``*_last_verified_at`` does
    NOT (the canonical "stop the verified clock" behavior).
  - ``GET /dns-state`` populates ``current_value`` + ``drift`` and updates
    the per-record audit timestamps WITHOUT flipping the canonical
    ``*_verified`` booleans.
  - Multi-string TXT rdata is concatenated WITHOUT any separator — the
    DKIM-with-stray-space scenario that motivated this work.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import Any

import dns.resolver
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domains.models import Domain
from app.domains.service import _join_txt_rdata

# ── DNS resolver stub helpers ─────────────────────────────────────


class _MxRdata:
    """Minimal stand-in for ``dns.rdtypes.IN.MX.MX``."""

    def __init__(self, exchange: str, preference: int = 10) -> None:
        # ``_check_mx`` reads ``.exchange`` and ``.preference``.
        self.exchange = exchange
        self.preference = preference


class _TxtRdata:
    """Minimal stand-in for ``dns.rdtypes.ANY.TXT.TXT``.

    The real type exposes ``.strings: tuple[bytes, ...]`` — which is exactly
    what ``_join_txt_rdata`` consumes.
    """

    def __init__(self, *chunks: bytes) -> None:
        self.strings: tuple[bytes, ...] = tuple(chunks)


# DNS_PLAN maps (qname, rdtype) -> iterable of rdata objects.
DnsPlan = dict[tuple[str, str], list[Any]]


def _install_resolver_stub(monkeypatch: pytest.MonkeyPatch, plan: DnsPlan) -> None:
    """Replace ``dns.resolver.resolve`` with a deterministic table lookup."""

    def _fake_resolve(qname: str, rdtype: str, *args: Any, **kwargs: Any) -> Iterable[Any]:
        key = (qname.rstrip("."), rdtype)
        if key not in plan:
            raise dns.resolver.NXDOMAIN
        return plan[key]

    monkeypatch.setattr(dns.resolver, "resolve", _fake_resolve)


_TEST_HOSTNAME: str = "mail.example.com"


def _pin_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``settings.hostname`` so the verify code resolves predictably."""
    from app.config import settings

    monkeypatch.setattr(settings, "hostname", _TEST_HOSTNAME, raising=False)


def _build_full_plan(
    *,
    domain: str,
    hostname: str,
    selector: str,
    dkim_value: str,
    dmarc_value: str | None = None,
    spf_value: str | None = None,
) -> DnsPlan:
    """Build a DNS plan where every required record is published correctly."""
    spf_value = spf_value or f"v=spf1 mx a:{hostname} ~all"
    dmarc_value = dmarc_value or f"v=DMARC1; p=reject; rua=mailto:postmaster@{domain}"
    return {
        (domain, "MX"): [_MxRdata(f"{hostname}.")],
        (domain, "TXT"): [_TxtRdata(spf_value.encode())],
        (hostname, "TXT"): [_TxtRdata(b"v=spf1 a -all")],
        (f"{selector}._domainkey.{domain}", "TXT"): [_TxtRdata(dkim_value.encode())],
        (f"_dmarc.{domain}", "TXT"): [_TxtRdata(dmarc_value.encode())],
        (f"default._bimi.{domain}", "TXT"): [
            _TxtRdata(f"v=BIMI1; l=https://{hostname}/brand/logo.svg".encode())
        ],
        (f"_mta-sts.{domain}", "TXT"): [_TxtRdata(b"v=STSv1; id=42")],
        (f"_smtp._tls.{domain}", "TXT"): [
            _TxtRdata(f"v=TLSRPTv1; rua=mailto:tls-reports@{domain}".encode())
        ],
    }


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture()
async def seed_domain(_engine_and_session: Any) -> AsyncIterator[Domain]:
    """Insert a managed domain directly via SQLAlchemy.

    Going through ``POST /api/v1/domains`` would invoke ``opendkim-genkey``,
    ``postmap``, and ``postfix reload`` — none of which exist in a CI
    environment.  The DNS-verification logic under test does not depend on
    those side-effects.
    """
    _engine, factory = _engine_and_session  # type: tuple[Any, async_sessionmaker[Any]]

    dkim_value = "v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAv1c2dBGfRtest"
    async with factory() as session:
        domain = Domain(
            name="example.com",
            dkim_selector="mail",
            dkim_public_key_txt=dkim_value,
        )
        session.add(domain)
        await session.commit()
        await session.refresh(domain)

    yield domain


# ── Helpers ───────────────────────────────────────────────────────


_AUDIT_SLOTS: tuple[str, ...] = (
    "mx",
    "spf",
    "dkim",
    "dmarc",
    "mta_sts",
    "tls_rpt",
)


async def _reload_domain(factory: async_sessionmaker[Any], name: str) -> Domain:
    async with factory() as session:
        result = await session.execute(select(Domain).where(Domain.name == name))
        return result.scalar_one()


# ── Tests: TXT joining (the bug that motivated this work) ────────


def test_join_multistring_txt_has_no_separator() -> None:
    """RFC 6376 §3.6.2.2 / RFC 7208 §3.3 — concatenate with NO whitespace."""
    rdata = _TxtRdata(b"v=DKIM1; k=rsa; p=AAA", b"BBB")
    assert _join_txt_rdata(rdata) == "v=DKIM1; k=rsa; p=AAABBB"


def test_join_single_string_txt_unchanged() -> None:
    rdata = _TxtRdata(b"v=spf1 mx a:mail.example.com ~all")
    assert _join_txt_rdata(rdata) == "v=spf1 mx a:mail.example.com ~all"


# ── Tests: POST /verify-dns ───────────────────────────────────────


async def test_verify_dns_stamps_checked_and_verified_on_success(
    client: AsyncClient,
    seed_domain: Domain,
    monkeypatch: pytest.MonkeyPatch,
    _engine_and_session: Any,
) -> None:
    _engine, factory = _engine_and_session
    plan = _build_full_plan(
        domain=seed_domain.name,
        hostname="mail.example.com",
        selector=seed_domain.dkim_selector,
        dkim_value=seed_domain.dkim_public_key_txt or "",
    )
    _pin_hostname(monkeypatch)
    _install_resolver_stub(monkeypatch, plan)

    resp = await client.post(f"/api/v1/domains/{seed_domain.name}/verify-dns")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["all_verified"] is True

    # Per-record current_value + drift surface in the response.
    by_type: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in body["dns_records"]:
        # MX is the only non-TXT canonical record; everything else is TXT
        # but is differentiated by hostname.
        by_type[(rec["record_type"], rec["hostname"])] = rec
    mx_rec = by_type[("MX", seed_domain.name)]
    assert mx_rec["current_value"] == "10 mail.example.com."
    assert mx_rec["drift"] is False

    # Audit timestamps were written for every canonical record.
    refreshed = await _reload_domain(factory, seed_domain.name)
    for slot in _AUDIT_SLOTS:
        assert getattr(refreshed, f"{slot}_last_checked_at") is not None, slot
        assert getattr(refreshed, f"{slot}_last_verified_at") is not None, slot


async def test_verify_dns_drift_advances_checked_but_not_verified(
    client: AsyncClient,
    seed_domain: Domain,
    monkeypatch: pytest.MonkeyPatch,
    _engine_and_session: Any,
) -> None:
    """When DKIM is published but does not match the expected value, the
    canonical *_verified booleans go False AND ``dkim_last_verified_at``
    must NOT be advanced — the drift indicator depends on this."""
    _engine, factory = _engine_and_session
    plan = _build_full_plan(
        domain=seed_domain.name,
        hostname="mail.example.com",
        selector=seed_domain.dkim_selector,
        dkim_value="v=DKIM1; k=rsa; p=DRIFTED_KEY",  # mismatch
    )
    _pin_hostname(monkeypatch)
    _install_resolver_stub(monkeypatch, plan)

    resp = await client.post(f"/api/v1/domains/{seed_domain.name}/verify-dns")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dkim_verified"] is False
    assert body["all_verified"] is False

    # The DKIM record in the response should report the published (drifted)
    # value and drift=True.
    dkim_rec = next(
        r
        for r in body["dns_records"]
        if r["record_type"] == "TXT"
        and r["hostname"].startswith(f"{seed_domain.dkim_selector}._domainkey.")
    )
    assert dkim_rec["current_value"] == "v=DKIM1; k=rsa; p=DRIFTED_KEY"
    assert dkim_rec["drift"] is True
    assert dkim_rec["last_checked_at"] is not None
    assert dkim_rec["last_verified_at"] is None  # never verified before

    refreshed = await _reload_domain(factory, seed_domain.name)
    assert refreshed.dkim_last_checked_at is not None
    assert refreshed.dkim_last_verified_at is None
    # The other records DID verify — sanity-check spf advanced both stamps.
    assert refreshed.spf_last_checked_at is not None
    assert refreshed.spf_last_verified_at is not None


async def test_verify_dns_with_multistring_dkim_concatenates_without_space(
    client: AsyncClient,
    seed_domain: Domain,
    monkeypatch: pytest.MonkeyPatch,
    _engine_and_session: Any,
) -> None:
    """The exact regression: a DKIM TXT split into multiple
    ``<character-string>``s must concatenate WITHOUT a space, otherwise
    the published ``p=`` blob gets a stray space and verification fails."""
    del _engine_and_session  # unused; resolver is mocked via monkeypatch
    expected = seed_domain.dkim_public_key_txt or ""
    # Split the expected value at an arbitrary boundary so that naive
    # ``str(rdata)`` would re-introduce a separator.
    split_at = len(expected) // 2
    chunk_a, chunk_b = expected[:split_at], expected[split_at:]
    plan = _build_full_plan(
        domain=seed_domain.name,
        hostname="mail.example.com",
        selector=seed_domain.dkim_selector,
        dkim_value="UNUSED — replaced below",
    )
    plan[(f"{seed_domain.dkim_selector}._domainkey.{seed_domain.name}", "TXT")] = [
        _TxtRdata(chunk_a.encode(), chunk_b.encode())
    ]
    _pin_hostname(monkeypatch)
    _install_resolver_stub(monkeypatch, plan)

    resp = await client.post(f"/api/v1/domains/{seed_domain.name}/verify-dns")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dkim_verified"] is True, body
    assert body["all_verified"] is True


# ── Tests: GET /dns-state ─────────────────────────────────────────


async def test_dns_state_reports_drift_without_flipping_verified(
    client: AsyncClient,
    seed_domain: Domain,
    monkeypatch: pytest.MonkeyPatch,
    _engine_and_session: Any,
) -> None:
    """Pre-condition: the canonical booleans say "verified" (e.g. a
    previous successful POST /verify-dns).  When DNS subsequently drifts,
    GET /dns-state must surface ``drift=True`` AND keep the canonical
    booleans untouched (production-mode gates depend on them)."""
    _engine, factory = _engine_and_session

    # Mark canonical state as "all green" — simulating a prior successful
    # verify.  ``compute_dns_state`` must not undo this on drift.
    async with factory() as session:
        result = await session.execute(select(Domain).where(Domain.name == seed_domain.name))
        d = result.scalar_one()
        d.mx_verified = True
        d.spf_verified = True
        d.dkim_verified = True
        d.dmarc_verified = True
        d.mta_sts_verified = True
        d.tls_rpt_verified = True
        await session.commit()

    plan = _build_full_plan(
        domain=seed_domain.name,
        hostname="mail.example.com",
        selector=seed_domain.dkim_selector,
        dkim_value=seed_domain.dkim_public_key_txt or "",
        spf_value="v=spf1 -all",  # drifted SPF
    )
    _pin_hostname(monkeypatch)
    _install_resolver_stub(monkeypatch, plan)

    resp = await client.get(f"/api/v1/domains/{seed_domain.name}/dns-state")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["domain"] == seed_domain.name
    assert body["has_drift"] is True
    assert body["has_missing"] is False
    assert body["last_dns_check"] is not None

    # SPF record specifically should report drift with the published value.
    spf_rec = next(
        r
        for r in body["records"]
        if r["record_type"] == "TXT" and r["hostname"] == seed_domain.name
    )
    assert spf_rec["current_value"] == "v=spf1 -all"
    assert spf_rec["drift"] is True
    assert spf_rec["last_checked_at"] is not None

    # Canonical booleans MUST be untouched by /dns-state.
    refreshed = await _reload_domain(factory, seed_domain.name)
    assert refreshed.mx_verified is True
    assert refreshed.spf_verified is True
    assert refreshed.dkim_verified is True
    assert refreshed.dmarc_verified is True
    assert refreshed.mta_sts_verified is True
    assert refreshed.tls_rpt_verified is True

    # But audit timestamps DID advance.
    assert refreshed.spf_last_checked_at is not None


async def test_dns_state_missing_record_marks_has_missing(
    client: AsyncClient,
    seed_domain: Domain,
    monkeypatch: pytest.MonkeyPatch,
    _engine_and_session: Any,
) -> None:
    """If no record is published for a canonical type, ``has_missing`` is
    True and ``current_value`` is None for that record."""
    plan = _build_full_plan(
        domain=seed_domain.name,
        hostname="mail.example.com",
        selector=seed_domain.dkim_selector,
        dkim_value=seed_domain.dkim_public_key_txt or "",
    )
    # Remove DMARC entirely — the resolver will raise NXDOMAIN.
    plan.pop((f"_dmarc.{seed_domain.name}", "TXT"), None)
    _pin_hostname(monkeypatch)
    _install_resolver_stub(monkeypatch, plan)

    resp = await client.get(f"/api/v1/domains/{seed_domain.name}/dns-state")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_missing"] is True

    dmarc_rec = next(
        r
        for r in body["records"]
        if r["record_type"] == "TXT" and r["hostname"] == f"_dmarc.{seed_domain.name}"
    )
    assert dmarc_rec["current_value"] is None
    assert dmarc_rec["drift"] is False  # cannot drift if not published
    assert dmarc_rec["last_checked_at"] is not None
