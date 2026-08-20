"""Passive risk signals for a recipient domain.

None of these need delivery history or an SMTP conversation, so they apply on
the first sighting of a domain. They answer a different question from the RCPT
probe: not "does this mailbox exist" but "is this domain a maintained mail
destination at all". A domain registered three weeks ago behind parking
nameservers behaves nothing like a fourteen-year-old domain publishing MTA-STS,
even when both accept every recipient.

An SPF record also identifies the mailbox backend hiding behind a security
gateway, which is the layer that actually generates the asynchronous bounce.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app.config import settings
from app.emails.dns_resolver import resolve, resolve_txt

logger = logging.getLogger("mailcue.domain_signals")

_RDAP_ENDPOINT = "https://rdap.org/domain/"
_CACHE_TTL_SECONDS = 3600.0
_CACHE_MAX_ENTRIES = 4096

_cache: dict[str, tuple[float, DomainSignals]] = {}
_cache_lock = asyncio.Lock()

PARKING_NAMESERVERS: tuple[str, ...] = (
    "sedoparking.com",
    "parkingcrew.net",
    "bodis.com",
    "above.com",
    "afternic.com",
    "dan.com",
    "undeveloped.com",
    "sav.com",
    "parklogic.com",
    "parkingpanel.com",
    "voodoo.com",
    "domaincntrol.com",
    "fabulous.com",
)

_BACKEND_SPF_HINTS: tuple[tuple[str, str], ...] = (
    ("spf.protection.outlook.com", "microsoft365"),
    ("protection.office365.us", "microsoft365"),
    ("_spf.google.com", "google_workspace"),
    ("spf.zoho.com", "zoho"),
    ("spf.messagingengine.com", "fastmail"),
    ("_spf.protonmail.ch", "proton"),
    ("spf.mail.yandex.net", "yandex"),
    ("amazonses.com", "amazon_workmail"),
)

_DMARC_POLICY = re.compile(r"\bp\s*=\s*(none|quarantine|reject)\b", re.IGNORECASE)


@dataclass
class DomainSignals:
    """Passive evidence about a recipient domain."""

    domain: str
    age_days: int | None = None
    registered_at: datetime | None = None
    expires_at: datetime | None = None
    expires_in_days: int | None = None
    has_spf: bool = False
    spf_record: str | None = None
    has_dmarc: bool = False
    dmarc_policy: str | None = None
    has_mta_sts: bool = False
    has_tls_rpt: bool = False
    wildcard_dns: bool = False
    parked: bool = False
    inferred_backend: str | None = None
    risk_delta: float = 0.0
    notes: list[str] = field(default_factory=list)


def _parse_rdap_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def _fetch_rdap(domain: str) -> tuple[datetime | None, datetime | None]:
    """Look up registration and expiry dates over RDAP.

    RDAP is used instead of WHOIS because it is JSON, has stable rate limits,
    and does not need per-registry response parsing.
    """
    if not settings.validation_rdap_enabled:
        return None, None
    try:
        async with httpx.AsyncClient(
            timeout=settings.validation_rdap_timeout_seconds,
            follow_redirects=True,
        ) as client:
            response = await client.get(
                f"{_RDAP_ENDPOINT}{domain}",
                headers={"Accept": "application/rdap+json"},
            )
        if response.status_code != 200:
            return None, None
        payload = response.json()
    except Exception as exc:
        logger.debug("RDAP lookup failed for %s: %s", domain, exc)
        return None, None

    registered: datetime | None = None
    expires: datetime | None = None
    for event in payload.get("events", []) or []:
        action = str(event.get("eventAction", "")).lower()
        stamp = event.get("eventDate")
        if not isinstance(stamp, str):
            continue
        parsed = _parse_rdap_timestamp(stamp)
        if parsed is None:
            continue
        if action == "registration" and registered is None:
            registered = parsed
        elif action == "expiration" and expires is None:
            expires = parsed
    return registered, expires


async def _has_wildcard_dns(domain: str) -> bool:
    """Detect a wildcard record by resolving a label that cannot legitimately exist."""
    probe = f"mailcue-wildcard-probe-7f3a91.{domain}"
    answers = await resolve(probe, "A")
    return bool(answers)


async def _collect(domain: str) -> DomainSignals:
    signals = DomainSignals(domain=domain)

    # gather() collapses heterogeneous results to a common supertype, so the
    # tasks are awaited individually after being started together.
    spf_task = asyncio.ensure_future(resolve_txt(domain))
    dmarc_task = asyncio.ensure_future(resolve_txt(f"_dmarc.{domain}"))
    mta_sts_task = asyncio.ensure_future(resolve_txt(f"_mta-sts.{domain}"))
    tls_rpt_task = asyncio.ensure_future(resolve_txt(f"_smtp._tls.{domain}"))
    ns_task = asyncio.ensure_future(resolve(domain, "NS"))
    wildcard_task = asyncio.ensure_future(_has_wildcard_dns(domain))
    rdap_task = asyncio.ensure_future(_fetch_rdap(domain))
    await asyncio.gather(
        spf_task,
        dmarc_task,
        mta_sts_task,
        tls_rpt_task,
        ns_task,
        wildcard_task,
        rdap_task,
        return_exceptions=True,
    )

    spf_txt = spf_task.result() if not spf_task.cancelled() else []
    dmarc_txt = dmarc_task.result() if not dmarc_task.cancelled() else []
    mta_sts_txt = mta_sts_task.result() if not mta_sts_task.cancelled() else []
    tls_rpt_txt = tls_rpt_task.result() if not tls_rpt_task.cancelled() else []
    ns_answers = ns_task.result() if not ns_task.cancelled() else []
    wildcard = wildcard_task.result() if not wildcard_task.cancelled() else False
    registered, expires = rdap_task.result() if not rdap_task.cancelled() else (None, None)

    for record in spf_txt:
        if record.lower().startswith("v=spf1"):
            signals.has_spf = True
            signals.spf_record = record[:512]
            lowered = record.lower()
            for hint, backend in _BACKEND_SPF_HINTS:
                if hint in lowered:
                    signals.inferred_backend = backend
                    break
            break

    for record in dmarc_txt:
        if record.lower().startswith("v=dmarc1"):
            signals.has_dmarc = True
            match = _DMARC_POLICY.search(record)
            if match:
                signals.dmarc_policy = match.group(1).lower()
            break

    signals.has_mta_sts = any(record.lower().startswith("v=stsv1") for record in mta_sts_txt)
    signals.has_tls_rpt = any(record.lower().startswith("v=tlsrptv1") for record in tls_rpt_txt)
    signals.wildcard_dns = wildcard

    nameservers = [str(getattr(rdata, "target", "")).rstrip(".").lower() for rdata in ns_answers]
    signals.parked = any(
        ns.endswith(parking) or ns == parking
        for ns in nameservers
        for parking in PARKING_NAMESERVERS
    )

    signals.registered_at = registered
    signals.expires_at = expires
    now = datetime.now(UTC)
    if registered is not None:
        signals.age_days = max((now - registered).days, 0)
    if expires is not None:
        signals.expires_in_days = (expires - now).days

    _score(signals)
    return signals


def _score(signals: DomainSignals) -> None:
    """Convert collected signals into an additive log-odds adjustment."""
    delta = 0.0
    notes: list[str] = []

    if signals.parked:
        delta += 2.5
        notes.append("Domain uses parking nameservers.")
    if signals.age_days is not None:
        if signals.age_days < 30:
            delta += 1.4
            notes.append(f"Domain was registered {signals.age_days} days ago.")
        elif signals.age_days < 180:
            delta += 0.6
            notes.append(f"Domain is {signals.age_days} days old.")
        elif signals.age_days > 3650:
            delta -= 0.2
            notes.append("Domain has been registered for over ten years.")
    if signals.expires_in_days is not None and signals.expires_in_days < 30:
        delta += 0.8
        notes.append(f"Domain registration expires in {signals.expires_in_days} days.")
    if not signals.has_spf:
        # The clearest passive signal in the measured cohort: 30% of addresses
        # at domains without SPF bounced, against a 14% base rate.
        delta += 0.6
        notes.append("Domain publishes no SPF record.")
    # Authentication and transport-security records were originally read as
    # evidence of a maintained mail domain. Measurement did not support it:
    # DMARC-publishing domains bounced at 13.5% against a 14.3% base rate, and
    # MTA-STS publishers bounced at 19.2%, worse than average. Both are now
    # reported for context without moving the estimate.
    if signals.has_dmarc:
        notes.append("Domain publishes DMARC.")
    if signals.has_mta_sts:
        notes.append("Domain publishes MTA-STS.")
    if signals.wildcard_dns and not signals.has_dmarc:
        delta += 0.3
        notes.append("Domain resolves wildcard hostnames.")
    if signals.inferred_backend:
        notes.append(f"SPF indicates a {signals.inferred_backend} mailbox backend.")

    signals.risk_delta = round(delta, 3)
    signals.notes = notes


async def collect_domain_signals(domain: str) -> DomainSignals:
    """Return cached passive signals for a domain, collecting them if needed."""
    key = domain.strip().lower()
    if not key:
        return DomainSignals(domain=key)

    now = time.monotonic()
    async with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]

    try:
        async with asyncio.timeout(settings.validation_domain_signal_timeout_seconds):
            signals = await _collect(key)
    except TimeoutError:
        logger.debug("Domain signal collection timed out for %s", key)
        signals = DomainSignals(domain=key)
    except Exception as exc:
        logger.debug("Domain signal collection failed for %s: %s", key, exc)
        signals = DomainSignals(domain=key)

    async with _cache_lock:
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            _cache.clear()
        _cache[key] = (now + _CACHE_TTL_SECONDS, signals)
    return signals


def clear_cache() -> None:
    """Drop cached signals. Used by tests and by administrative refreshes."""
    _cache.clear()
