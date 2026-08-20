"""Email validation business logic.

Provides functions to validate email address syntax, verify DNS (MX/NS/A)
records, run SMTP RCPT TO handshake probes, and check against disposable domains.

Accept-all detection uses several control recipients rather than one. A single
random control only proves that the destination accepts one obviously synthetic
address; receivers that reject machine-shaped local parts while accepting
plausible ones are indistinguishable from true accept-all domains under a
one-sample test. Probing controls of different shapes, and placing one control
ahead of the target so per-connection degradation can be recognised, separates
a genuine accept-all from a destination that is simply refusing to answer.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import random
import re
import secrets
import socket
import statistics
import time
from dataclasses import dataclass, field
from typing import Literal

import aiosmtplib
import dns.resolver

from app.config import settings
from app.emails.disposable import is_disposable_domain, is_forwarding_alias_domain
from app.emails.dns_resolver import resolver as _resolver
from app.emails.domain_signals import DomainSignals, collect_domain_signals
from app.emails.local_part import LocalPartSignals, analyze_local_part
from app.emails.mx_providers import MxProfile, MxProvider, classify_mx, parse_mx_hosts
from app.emails.risk_model import ProbeEvidence as ProbeEvidenceInput
from app.emails.schemas import (
    EmailValidationControlProbe,
    EmailValidationDisposable,
    EmailValidationDns,
    EmailValidationDomainSignals,
    EmailValidationLocalPart,
    EmailValidationMailbox,
    EmailValidationProvider,
    EmailValidationResponse,
    EmailValidationSyntax,
)
from app.emails.smtp_reply import RcptClassification, classify_rcpt_response

logger = logging.getLogger("mailcue.validation")

# Robust email regex according to RFCs (allowing standard characters)
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)

# RFC 2606 reserved domains and common internal-only TLDs
RESERVED_TLDS = {
    "local",
    "localhost",
    "test",
    "example",
    "invalid",
    "internal",
    "lan",
    "home.arpa",
}

_CONTROL_FIRST_NAMES = (
    "adrian",
    "bernice",
    "callum",
    "delphine",
    "edmund",
    "fiona",
    "gareth",
    "harriet",
    "ingrid",
    "julius",
    "kirsten",
    "lorcan",
    "marguerite",
    "nolan",
    "ottoline",
    "perrin",
)
_CONTROL_SURNAMES = (
    "ashcroft",
    "beaumont",
    "castellan",
    "dunmore",
    "ellingham",
    "fairweather",
    "grantley",
    "harkness",
    "inglethorpe",
    "jarvis",
    "kingsleigh",
    "lattimer",
    "mordaunt",
    "northwood",
    "oakhurst",
    "pemberton",
)
_LETTERS = "abcdefghijklmnopqrstuvwxyz"


@dataclass
class ProbeAttempt:
    """One RCPT TO exchange and how long the destination took to answer."""

    label: str
    recipient: str
    code: int | None
    message: str
    classification: RcptClassification
    latency_ms: float


@dataclass
class ProbeSession:
    """Everything one destination told us about a target and its controls."""

    target: ProbeAttempt | None = None
    controls: list[ProbeAttempt] = field(default_factory=list)
    # True when the first control was accepted but a later one was refused,
    # which usually means the connection degraded rather than that the
    # destination validates recipients.
    order_degraded: bool = False


def _random_token(length: int, alphabet: str = _LETTERS) -> str:
    return "".join(secrets.choice(alphabet) for _ in range(length))


def build_control_locals(target_local: str, count: int) -> list[str]:
    """Build nonexistent local parts of several shapes for accept-all testing.

    The shapes are deliberately different from each other. A destination that
    answers them all the same way is genuinely accepting everything; one that
    distinguishes between them is applying recipient logic, and its answer for
    the real address means something.
    """
    controls: list[str] = []

    # A plausible human address catches receivers that only refuse obviously
    # synthetic recipients. Four random digits keep collisions negligible.
    first = secrets.choice(_CONTROL_FIRST_NAMES)
    surname = secrets.choice(_CONTROL_SURNAMES)
    controls.append(f"{first}.{surname}{secrets.randbelow(9000) + 1000}")

    # A shape-matched control has the same separators and token lengths as the
    # address under test, so pattern-based recipient rules treat it alike.
    shaped = _shape_matched_local(target_local)
    if shaped:
        controls.append(shaped)

    # A high-entropy control is the classic accept-all test.
    controls.append(_random_token(20, "0123456789abcdef"))

    unique: list[str] = []
    for value in controls:
        if value and value.lower() != target_local.lower() and value not in unique:
            unique.append(value)
    return unique[: max(count, 1)]


def _shape_matched_local(target_local: str) -> str:
    """Mirror the separator layout and token lengths of the target local part."""
    base = target_local.split("+", 1)[0]
    if not base or len(base) > 64:
        return ""
    parts = re.split(r"([._\-])", base)
    rebuilt: list[str] = []
    total_random = 0
    for part in parts:
        if part in {".", "_", "-"}:
            rebuilt.append(part)
            continue
        if not part:
            continue
        length = min(len(part), 20)
        rebuilt.append(_random_token(length))
        total_random += length
    candidate = "".join(rebuilt)
    if not candidate:
        return ""
    # Short random strings can collide with a real mailbox, which would look
    # like an accept-all. Extend them until a collision is implausible.
    if total_random < 6:
        candidate = f"{candidate}{_random_token(6 - total_random)}"
    return candidate[:64]


async def _resolve_public_smtp_addresses(host: str) -> list[str]:
    """Resolve one MX hostname and retain only globally routable addresses."""
    resolved = await asyncio.get_running_loop().getaddrinfo(host, 25, type=socket.SOCK_STREAM)
    addresses: list[str] = []
    for entry in resolved:
        address = ipaddress.ip_address(entry[4][0])
        if address.is_global:
            addresses.append(str(address))
    return addresses


def validate_syntax(email: str) -> EmailValidationSyntax:
    """Validate the syntax of an email address, rejecting reserved/internal domains."""
    email = email.strip()
    if not email or "@" not in email:
        return EmailValidationSyntax(
            is_valid=False,
            error="Email address must contain exactly one '@' character",
        )

    parts = email.split("@")
    if len(parts) != 2:
        return EmailValidationSyntax(
            is_valid=False,
            error="Email address must contain exactly one '@' character",
        )

    local_part, domain = parts

    if len(email) > 254:
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error="Email address exceeds maximum length of 254 characters",
        )
    if len(local_part) > 64:
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error="Local part exceeds maximum length of 64 characters",
        )
    if len(domain) > 255:
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error="Domain part exceeds maximum length of 255 characters",
        )

    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except Exception as exc:
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error=f"Invalid IDN domain: {exc}",
        )

    ascii_email = f"{local_part}@{ascii_domain}"
    if not EMAIL_REGEX.match(ascii_email):
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error="Invalid email address syntax",
        )

    # Check domain label lengths and hyphens
    if local_part.startswith(".") or local_part.endswith(".") or ".." in local_part:
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error="Local part cannot start or end with a dot or contain consecutive dots",
        )

    domain_labels = ascii_domain.split(".")
    if len(domain_labels) < 2:
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error="Domain must contain at least one dot (e.g., domain.com)",
        )

    for label in domain_labels:
        if not label:
            return EmailValidationSyntax(
                is_valid=False,
                local_part=local_part,
                domain=domain,
                error="Domain labels cannot be empty",
            )
        if len(label) > 63:
            return EmailValidationSyntax(
                is_valid=False,
                local_part=local_part,
                domain=domain,
                error=f"Domain label '{label}' exceeds maximum length of 63 characters",
            )
        if label.startswith("-") or label.endswith("-"):
            return EmailValidationSyntax(
                is_valid=False,
                local_part=local_part,
                domain=domain,
                error=f"Domain label '{label}' cannot start or end with a hyphen",
            )

    tld = domain_labels[-1]
    if len(tld) < 2:
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error="Top-level domain (TLD) must be at least 2 characters",
        )
    if not re.match(r"^[a-zA-Z0-9-]+$", tld):
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error="Top-level domain (TLD) contains invalid characters",
        )

    # Reject internal or reserved TLDs
    tld_lower = tld.lower()
    if tld_lower in RESERVED_TLDS:
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error=f"Domain uses a reserved or internal top-level domain: .{tld_lower}",
        )

    # Reject RFC 2606 reserved domains
    domain_lower = domain.lower()
    if (
        domain_lower == "example.com"
        or domain_lower.endswith(".example.com")
        or domain_lower == "example.net"
        or domain_lower.endswith(".example.net")
        or domain_lower == "example.org"
        or domain_lower.endswith(".example.org")
    ):
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error="Domain is reserved for testing/examples",
        )

    return EmailValidationSyntax(
        is_valid=True,
        local_part=local_part,
        domain=ascii_domain.lower(),
    )


async def validate_dns(domain: str) -> EmailValidationDns:
    """Resolve the records that SMTP delivery actually uses.

    NXDOMAIN/null-MX are definitive failures. Resolver timeouts and SERVFAIL
    remain undetermined so a temporary DNS incident never labels a mailbox dead.
    """
    has_mx = False
    has_ns = False
    has_a = False
    has_aaaa = False
    null_mx = False
    mx_records: list[tuple[int, str]] = []
    ns_records: list[str] = []
    a_records: list[str] = []
    aaaa_records: list[str] = []
    errors: list[Exception] = []

    # IDNA encoding for domains
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except Exception:
        ascii_domain = domain

    async def resolve_mx() -> None:
        nonlocal has_mx, null_mx, mx_records
        try:
            answers = await asyncio.to_thread(_resolver.resolve, ascii_domain, "MX")
            for rdata in answers:
                pref = getattr(rdata, "preference", 0)
                raw_exchange = str(getattr(rdata, "exchange", ""))
                if raw_exchange == ".":
                    null_mx = True
                    continue
                exchange = raw_exchange.rstrip(".")
                if exchange:
                    mx_records.append((pref, exchange))
            mx_records.sort()
            has_mx = len(mx_records) > 0
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            return
        except Exception as exc:
            errors.append(exc)

    async def resolve_ns() -> None:
        nonlocal has_ns, ns_records
        try:
            answers = await asyncio.to_thread(_resolver.resolve, ascii_domain, "NS")
            for rdata in answers:
                ns_host = str(getattr(rdata, "target", "")).rstrip(".")
                if ns_host:
                    ns_records.append(ns_host)
            has_ns = len(ns_records) > 0
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            return
        except Exception as exc:
            errors.append(exc)

    async def resolve_a() -> None:
        nonlocal has_a, a_records
        try:
            answers = await asyncio.to_thread(_resolver.resolve, ascii_domain, "A")
            for rdata in answers:
                address = str(getattr(rdata, "address", ""))
                if address:
                    a_records.append(address)
            has_a = len(a_records) > 0
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            return
        except Exception as exc:
            errors.append(exc)

    async def resolve_aaaa() -> None:
        nonlocal has_aaaa, aaaa_records
        try:
            answers = await asyncio.to_thread(_resolver.resolve, ascii_domain, "AAAA")
            for rdata in answers:
                address = str(getattr(rdata, "address", ""))
                if address:
                    aaaa_records.append(address)
            has_aaaa = len(aaaa_records) > 0
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            return
        except Exception as exc:
            errors.append(exc)

    await asyncio.gather(resolve_mx(), resolve_ns(), resolve_a(), resolve_aaaa())

    # RFC 5321 implicit MX permits A or AAAA when no MX exists. A separate
    # NS lookup is diagnostic only and is not a delivery prerequisite.
    is_valid = not null_mx and (has_mx or has_a or has_aaaa)

    formatted_mx = [f"{pref} {host}." for pref, host in mx_records]
    formatted_ns = [f"{host}." for host in ns_records]

    status: Literal["valid", "invalid", "undetermined"] = "valid" if is_valid else "invalid"
    error = None
    error_code = None
    if null_mx:
        error_code = "null_mx"
        error = "Domain publishes a null MX and does not accept email"
    elif not is_valid and errors:
        status = "undetermined"
        error_code = "dns_temporary_failure"
        error = f"DNS lookup temporarily failed: {errors[0]}"
    elif not is_valid:
        error_code = "no_mail_route"
        error = "No MX, A, or AAAA records found; domain cannot receive mail"

    return EmailValidationDns(
        is_valid=is_valid,
        has_mx=has_mx,
        has_ns=has_ns,
        has_a=has_a,
        has_aaaa=has_aaaa,
        null_mx=null_mx,
        mx_records=formatted_mx,
        ns_records=formatted_ns,
        a_records=a_records,
        aaaa_records=aaaa_records,
        status=status,
        error_code=error_code,
        error=error,
    )


async def _rcpt_probe(
    smtp: aiosmtplib.SMTP,
    *,
    label: str,
    recipient: str,
    sender_email: str,
    provider: MxProvider | None,
) -> ProbeAttempt | None:
    """Run one RCPT TO in its own envelope and time the destination's answer.

    Each probe gets a fresh MAIL FROM so per-envelope recipient limits and
    policy cannot let one probe distort the next.
    """
    with contextlib.suppress(Exception):
        await smtp.rset()

    sender_ok = False
    for sender in (sender_email, ""):
        try:
            code, _ = await smtp.mail(sender)
            if 200 <= code < 300:
                sender_ok = True
                break
        except aiosmtplib.SMTPResponseException:
            pass
        with contextlib.suppress(Exception):
            await smtp.rset()
    if not sender_ok:
        return None

    started = time.monotonic()
    try:
        code, message = await smtp.rcpt(recipient)
    except aiosmtplib.SMTPResponseException as exc:
        code, message = int(exc.code or 0), exc.message
    latency_ms = (time.monotonic() - started) * 1000
    text = _smtp_text(message)
    return ProbeAttempt(
        label=label,
        recipient=recipient,
        code=code,
        message=text,
        classification=classify_rcpt_response(code, text, provider),
        latency_ms=round(latency_ms, 2),
    )


async def _run_probe_session(
    smtp: aiosmtplib.SMTP,
    *,
    target_email: str,
    sender_email: str,
    domain: str,
    provider: MxProvider | None,
    control_count: int,
) -> ProbeSession:
    """Probe the target alongside control recipients on one connection.

    One control is sent before the target. Destinations that tarpit or degrade
    after the first recipient in a session would otherwise make every control
    look rejected, which reads as recipient validation when it is really just
    throttling.
    """
    session = ProbeSession()
    if control_count <= 0:
        session.target = await _rcpt_probe(
            smtp,
            label="target",
            recipient=target_email,
            sender_email=sender_email,
            provider=provider,
        )
        return session

    local_part = target_email.rsplit("@", 1)[0]
    controls = build_control_locals(local_part, control_count)
    random.shuffle(controls)

    leading = controls[:1]
    trailing = controls[1:]

    for index, control_local in enumerate(leading):
        attempt = await _rcpt_probe(
            smtp,
            label=f"control_{index}",
            recipient=f"{control_local}@{domain}",
            sender_email=sender_email,
            provider=provider,
        )
        if attempt is not None:
            session.controls.append(attempt)

    session.target = await _rcpt_probe(
        smtp,
        label="target",
        recipient=target_email,
        sender_email=sender_email,
        provider=provider,
    )
    if session.target is None:
        return session

    # A rejected target settles the question; further controls only cost the
    # destination extra connections.
    if session.target.classification.verdict != "mailbox_present":
        return session

    for offset, control_local in enumerate(trailing, start=len(leading)):
        attempt = await _rcpt_probe(
            smtp,
            label=f"control_{offset}",
            recipient=f"{control_local}@{domain}",
            sender_email=sender_email,
            provider=provider,
        )
        if attempt is None:
            break
        session.controls.append(attempt)

    if session.controls:
        first = session.controls[0]
        later_rejected = any(control.classification.is_absent for control in session.controls[1:])
        session.order_degraded = first.classification.is_present and later_rejected

    return session


def _mailbox_from_session(
    session: ProbeSession,
    *,
    transport: Literal["direct", "mailcue_tunnel", "none"],
    profile: MxProfile | None,
) -> EmailValidationMailbox:
    """Turn probe observations into a mailbox result."""
    target = session.target
    if target is None:
        return EmailValidationMailbox(
            is_valid=None,
            transport=transport,
            reason_code="smtp_unreachable",
            error="Destination did not accept a probe envelope",
        )

    control_probes = [
        EmailValidationControlProbe(
            shape=control.label,
            smtp_code=control.code,
            smtp_response=control.message[:255],
            verdict=control.classification.verdict,
            latency_ms=control.latency_ms,
        )
        for control in session.controls
    ]
    control_latencies = [control.latency_ms for control in session.controls]
    control_median = round(statistics.median(control_latencies), 2) if control_latencies else None
    accepted_controls = sum(1 for c in session.controls if c.classification.is_present)
    rejected_controls = sum(1 for c in session.controls if c.classification.is_absent)
    inconclusive_controls = len(session.controls) - accepted_controls - rejected_controls

    verdict = target.classification.verdict
    catch_all: bool | None = None
    selective: bool | None = None
    if session.controls:
        if rejected_controls and not session.order_degraded:
            selective = True
        elif accepted_controls == len(session.controls):
            selective = False
        if verdict == "mailbox_present":
            if accepted_controls == len(session.controls) and accepted_controls > 0:
                catch_all = True
            elif rejected_controls and not session.order_degraded:
                catch_all = False
    if verdict == "mailbox_absent":
        catch_all = False

    if verdict == "mailbox_present":
        is_valid: bool | None = True
        reason_code = "accept_all_domain" if catch_all else "mailbox_accepted"
        error = None
    elif verdict == "mailbox_absent":
        is_valid = False
        reason_code = "mailbox_rejected"
        error = None
    elif verdict == "temporary":
        is_valid = None
        reason_code = "smtp_temporary_failure"
        error = f"Temporary SMTP failure: {target.message}"
    else:
        is_valid = None
        reason_code = target.classification.reason_code
        error = "SMTP policy rejection did not prove that the mailbox is absent"

    return EmailValidationMailbox(
        is_valid=is_valid,
        smtp_code=target.code,
        smtp_response=target.message,
        catch_all=catch_all,
        transport=transport,
        reason_code=reason_code,
        error=error,
        enhanced_status=target.classification.enhanced_status,
        target_latency_ms=target.latency_ms,
        control_median_latency_ms=control_median,
        control_probes=control_probes,
        controls_accepted=accepted_controls,
        controls_rejected=rejected_controls,
        controls_inconclusive=inconclusive_controls,
        selective_recipient_validation=selective,
        order_degraded=session.order_degraded,
        sender_reputation_signal=target.classification.sender_reputation_signal
        or any(c.classification.sender_reputation_signal for c in session.controls),
        mx_host=profile.matched_host if profile else None,
    )


async def validate_mailbox(
    domain: str,
    mx_records: list[str],
    target_email: str,
    sender_email: str,
    profile: MxProfile | None = None,
    control_probe_count: int | None = None,
) -> EmailValidationMailbox:
    """Run a direct, non-delivery SMTP envelope probe against destination MXs."""
    if not settings.validation_smtp_probe_enabled:
        return EmailValidationMailbox(
            is_valid=None,
            transport="none",
            reason_code="smtp_probe_disabled",
            error="SMTP probe disabled by configuration",
        )

    hosts = parse_mx_hosts(mx_records) or [domain]
    provider = profile.provider if profile else None
    control_count = (
        settings.validation_control_probe_count
        if control_probe_count is None
        else control_probe_count
    )

    last_error = None
    last_inconclusive: EmailValidationMailbox | None = None
    for host in hosts:
        try:
            public_addresses = await _resolve_public_smtp_addresses(host)
            if not public_addresses:
                logger.warning("Blocked SMTP probe to non-public destination %s", host)
                last_error = "MX host does not resolve to a public IP address"
                continue
            for address in public_addresses:
                smtp = aiosmtplib.SMTP(
                    hostname=address,
                    port=25,
                    timeout=settings.validation_smtp_timeout_seconds,
                )
                try:
                    await smtp.connect()
                    try:
                        await smtp.ehlo()
                    except Exception:
                        await smtp.helo()
                    # Some receivers only answer recipient questions honestly
                    # once the session is encrypted.
                    if smtp.supports_extension("starttls"):
                        with contextlib.suppress(Exception):
                            await smtp.starttls(validate_certs=False)
                            with contextlib.suppress(Exception):
                                await smtp.ehlo()

                    session = await _run_probe_session(
                        smtp,
                        target_email=target_email,
                        sender_email=sender_email,
                        domain=domain,
                        provider=provider,
                        control_count=control_count,
                    )
                    mailbox = _mailbox_from_session(session, transport="direct", profile=profile)
                    if mailbox.is_valid is not None:
                        return mailbox
                    last_inconclusive = mailbox
                    last_error = mailbox.error or last_error
                except Exception as exc:
                    last_error = str(exc)
                    if isinstance(exc, aiosmtplib.SMTPResponseException):
                        text = _smtp_text(exc.message)
                        classification = classify_rcpt_response(exc.code, text, provider)
                        last_inconclusive = EmailValidationMailbox(
                            is_valid=None,
                            smtp_code=exc.code,
                            smtp_response=text,
                            catch_all=None,
                            transport="direct",
                            reason_code="smtp_session_rejected",
                            error="SMTP session was rejected before recipient validation",
                            enhanced_status=classification.enhanced_status,
                            sender_reputation_signal=classification.sender_reputation_signal,
                            mx_host=host,
                        )
                    logger.debug("SMTP probe failed on %s (%s): %s", host, address, exc)
                finally:
                    if smtp.is_connected:
                        with contextlib.suppress(Exception):
                            await smtp.quit()
                        if smtp.is_connected:
                            smtp.close()
        except Exception as exc:
            last_error = str(exc)
            logger.debug("SMTP probe failed on host %s: %s", host, exc)

    return last_inconclusive or EmailValidationMailbox(
        is_valid=None,
        transport="direct",
        reason_code="smtp_unreachable",
        error=f"SMTP connection failed: {last_error or 'No hosts resolved'}",
    )


def _smtp_text(message: object) -> str:
    if isinstance(message, bytes):
        return message.decode("utf-8", errors="replace")
    return str(message)


_PROBE_FIELD_REGEX = re.compile(r"\b([a-z_]+)=([^\s]+)")


def _parse_probe_fields(text: str) -> dict[str, str]:
    """Read the key=value diagnostics the sidecar appends to a probe reply."""
    return {key: value for key, value in _PROBE_FIELD_REGEX.findall(text)}


def _probe_int(fields: dict[str, str], key: str) -> int | None:
    raw = fields.get(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _probe_float(fields: dict[str, str], key: str) -> float | None:
    raw = fields.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


async def validate_mailbox_via_tunnel(
    target_email: str,
    sender_email: str,
    profile: MxProfile | None = None,
    control_probe_count: int | None = None,
) -> EmailValidationMailbox:
    """Ask a MailCue sidecar to probe through its authenticated edge tunnel."""
    if not settings.validation_probe_relay_host:
        return EmailValidationMailbox(
            is_valid=None,
            transport="none",
            reason_code="probe_relay_not_configured",
            error="MailCue validation relay is not configured",
        )

    smtp = aiosmtplib.SMTP(
        hostname=settings.validation_probe_relay_host,
        port=settings.validation_probe_relay_port,
        timeout=settings.validation_smtp_timeout_seconds,
    )
    domain = target_email.rsplit("@", 1)[-1]
    started = time.monotonic()
    logger.info(
        "Starting mailbox probe through MailCue tunnel: domain=%s relay=%s:%s",
        domain,
        settings.validation_probe_relay_host,
        settings.validation_probe_relay_port,
    )
    try:
        await smtp.connect()
        await smtp.ehlo()
        if not smtp.supports_extension("XMAILCUEPROBE"):
            logger.error(
                "Validation relay does not advertise XMAILCUEPROBE: relay=%s:%s",
                settings.validation_probe_relay_host,
                settings.validation_probe_relay_port,
            )
            return EmailValidationMailbox(
                is_valid=None,
                transport="mailcue_tunnel",
                reason_code="probe_extension_unavailable",
                error="Configured validation relay does not support XMAILCUEPROBE",
            )
        code, message = await smtp.execute_command(
            b"XMAILCUEPROBE",
            target_email.encode("utf-8"),
            sender_email.encode("utf-8"),
            str(
                settings.validation_control_probe_count
                if control_probe_count is None
                else control_probe_count
            ).encode("utf-8"),
            timeout=max(
                settings.validation_smtp_timeout_seconds,
                settings.validation_total_timeout_seconds - 3,
            ),
        )
        text = _smtp_text(message)
        logger.info(
            "Mailbox tunnel probe completed: domain=%s code=%s duration_ms=%d",
            domain,
            code,
            round((time.monotonic() - started) * 1000),
        )
        fields = _parse_probe_fields(text)
        upstream_code = _probe_int(fields, "upstream_code")
        controls_total = _probe_int(fields, "controls_total") or 0
        controls_accepted = _probe_int(fields, "controls_accepted") or 0
        controls_rejected = _probe_int(fields, "controls_rejected") or 0
        controls_inconclusive = max(controls_total - controls_accepted - controls_rejected, 0)
        degraded = fields.get("degraded") == "1"
        reputation = fields.get("reputation") == "1"
        selective: bool | None = None
        if controls_total:
            if controls_rejected and not degraded:
                selective = True
            elif controls_accepted == controls_total:
                selective = False

        common = {
            "smtp_code": upstream_code,
            "smtp_response": text,
            "transport": "mailcue_tunnel",
            "enhanced_status": fields.get("enhanced"),
            "target_latency_ms": _probe_float(fields, "target_ms"),
            "control_median_latency_ms": _probe_float(fields, "control_ms"),
            "controls_accepted": controls_accepted,
            "controls_rejected": controls_rejected,
            "controls_inconclusive": controls_inconclusive,
            "selective_recipient_validation": selective,
            "order_degraded": degraded,
            "sender_reputation_signal": reputation,
            "mx_host": fields.get("mx"),
        }
        if code == 250:
            return EmailValidationMailbox(
                is_valid=True,
                catch_all=False,
                reason_code="mailbox_accepted",
                **common,
            )
        if code == 252:
            return EmailValidationMailbox(
                is_valid=True,
                catch_all=True,
                reason_code="accept_all_domain",
                **common,
            )
        if code == 550:
            return EmailValidationMailbox(
                is_valid=False,
                catch_all=False,
                reason_code="mailbox_rejected",
                **common,
            )
        return EmailValidationMailbox(
            is_valid=None,
            catch_all=None,
            reason_code="smtp_temporary_failure",
            error=text,
            **common,
        )
    except Exception as exc:
        logger.exception(
            "Mailbox tunnel probe failed: domain=%s relay=%s:%s duration_ms=%d",
            domain,
            settings.validation_probe_relay_host,
            settings.validation_probe_relay_port,
            round((time.monotonic() - started) * 1000),
        )
        return EmailValidationMailbox(
            is_valid=None,
            transport="mailcue_tunnel",
            reason_code="probe_relay_unreachable",
            error=f"MailCue validation relay failed: {exc}",
        )
    finally:
        if smtp.is_connected:
            with contextlib.suppress(Exception):
                await smtp.quit()


@dataclass
class ValidationOutcome:
    """A validation response plus the evidence the risk model needs.

    The response itself is serialisable and tenant-agnostic. The extra fields
    are what the router hands to the scoring layer, which needs a database
    session and therefore cannot live here.
    """

    response: EmailValidationResponse
    profile: MxProfile | None = None
    probe: ProbeEvidenceInput | None = None
    local_part_delta: float = 0.0
    local_part_notes: list[str] = field(default_factory=list)
    domain_signal_delta: float = 0.0
    domain_signal_notes: list[str] = field(default_factory=list)


def _provider_schema(
    profile: MxProfile, inferred_backend: str | None = None
) -> EmailValidationProvider:
    return EmailValidationProvider(
        id=profile.provider.id,
        name=profile.provider.name,
        category=profile.provider.category,
        matched_host=profile.matched_host,
        fronts_backend=profile.provider.fronts_backend,
        accept_all_bounce_prior=profile.provider.accept_all_bounce_prior,
        inferred_backend=inferred_backend,
        notes=profile.provider.notes,
    )


def _local_part_schema(signals: LocalPartSignals) -> EmailValidationLocalPart:
    return EmailValidationLocalPart(
        shape=signals.shape,
        is_role_account=signals.is_role_account,
        is_placeholder=signals.is_placeholder,
        is_trap_marker=signals.is_trap_marker,
        has_plus_tag=signals.has_plus_tag,
        gibberish_score=signals.gibberish_score,
        digit_ratio=signals.digit_ratio,
        risk_delta=signals.risk_delta,
        notes=signals.notes,
    )


def _domain_signal_schema(signals: DomainSignals) -> EmailValidationDomainSignals:
    return EmailValidationDomainSignals(
        age_days=signals.age_days,
        expires_in_days=signals.expires_in_days,
        has_spf=signals.has_spf,
        has_dmarc=signals.has_dmarc,
        dmarc_policy=signals.dmarc_policy,
        has_mta_sts=signals.has_mta_sts,
        has_tls_rpt=signals.has_tls_rpt,
        wildcard_dns=signals.wildcard_dns,
        parked=signals.parked,
        inferred_backend=signals.inferred_backend,
        risk_delta=signals.risk_delta,
        notes=signals.notes,
    )


def _probe_evidence(mailbox: EmailValidationMailbox) -> ProbeEvidenceInput:
    controls_total = (
        mailbox.controls_accepted + mailbox.controls_rejected + mailbox.controls_inconclusive
    )
    return ProbeEvidenceInput(
        accepted=mailbox.is_valid,
        control_total=controls_total,
        control_accepted=mailbox.controls_accepted,
        # Refusals that came only after an accepted control describe the
        # connection, not the recipient, so they are not counted as evidence
        # that the destination validates recipients.
        control_rejected=0 if mailbox.order_degraded else mailbox.controls_rejected,
        control_inconclusive=mailbox.controls_inconclusive,
        target_latency_ms=mailbox.target_latency_ms,
        control_median_latency_ms=mailbox.control_median_latency_ms,
        sender_reputation_signal=mailbox.sender_reputation_signal,
    )


async def validate_email_detailed(
    email: str,
    *,
    collect_signals: bool = True,
    control_probe_count: int | None = None,
) -> ValidationOutcome:
    """Validate one address and return the response together with risk evidence."""
    # 1. Syntax Check
    normalized_email = email.strip()
    syntax = validate_syntax(normalized_email)
    if not syntax.is_valid or not syntax.domain:
        return ValidationOutcome(
            response=EmailValidationResponse(
                email=normalized_email,
                is_valid=False,
                status="invalid",
                verdict="undeliverable",
                deliverable=False,
                confidence=1.0,
                reason="invalid_syntax",
                syntax=syntax,
                dns=EmailValidationDns(
                    is_valid=False,
                    has_mx=False,
                    has_ns=False,
                    has_a=False,
                    error="Syntax validation failed",
                ),
                mailbox=EmailValidationMailbox(is_valid=None, error="Syntax validation failed"),
                disposable=EmailValidationDisposable(is_disposable=False),
            )
        )

    domain = syntax.domain
    logger.info("Email validation started: domain=%s", domain)

    # 2. Disposable check (Fast offline check)
    is_disposable = is_disposable_domain(domain)
    disposable = EmailValidationDisposable(
        is_disposable=is_disposable,
        is_forwarding_alias=is_forwarding_alias_domain(domain),
    )

    # 3. Offline local-part evidence. This is the only signal that still says
    # anything once a destination accepts every recipient.
    local_signals = analyze_local_part(syntax.local_part or "")

    # 4. DNS check
    dns_res = await validate_dns(domain)
    logger.info(
        "Email validation DNS stage completed: domain=%s status=%s mx_count=%d",
        domain,
        dns_res.status,
        len(dns_res.mx_records),
    )
    if not dns_res.is_valid:
        return ValidationOutcome(
            response=EmailValidationResponse(
                email=normalized_email,
                is_valid=False,
                # A known disposable provider remains disposable even when its
                # DNS is temporarily unavailable (or DNS access is restricted in
                # the running environment). This classification is more specific
                # and does not depend on a live network lookup.
                status=(
                    "disposable"
                    if is_disposable
                    else "undetermined"
                    if dns_res.status == "undetermined"
                    else "invalid"
                ),
                verdict=(
                    "risky"
                    if is_disposable
                    else "unknown"
                    if dns_res.status == "undetermined"
                    else "undeliverable"
                ),
                deliverable=None if dns_res.status == "undetermined" else False,
                confidence=0.95 if dns_res.status == "invalid" else 0.2,
                reason=dns_res.error_code or "dns_validation_failed",
                syntax=syntax,
                dns=dns_res,
                mailbox=EmailValidationMailbox(is_valid=None, error="DNS validation failed"),
                disposable=disposable,
                local_part=_local_part_schema(local_signals),
            ),
            local_part_delta=local_signals.risk_delta,
            local_part_notes=local_signals.notes,
        )

    # 5. Classify the receiving provider. Whether an accept-all response means
    # anything at all is decided by who runs the destination mailbox, and a
    # gateway's definitive rejection codes differ from a mailbox host's.
    profile = classify_mx(parse_mx_hosts(dns_res.mx_records), domain)

    # 6. Passive domain evidence runs concurrently with nothing else pending, so
    # it is skipped when the caller does not need it.
    domain_sig: DomainSignals | None = None
    if collect_signals and settings.validation_domain_signals_enabled:
        domain_sig = await collect_domain_signals(domain)

    # 7. Mailbox check. A configured tunnel is the authoritative path for a
    # deployment whose host cannot reach destination MX servers on port 25;
    # trying every direct MX/IP first can exceed the caller's request timeout.
    # The total budget also bounds multi-address direct probes.
    sender_email = f"validate-probe@{settings.domain}"
    probe_transport: Literal["mailcue_tunnel", "direct"] = (
        "mailcue_tunnel" if settings.validation_probe_relay_host else "direct"
    )
    logger.info(
        "Starting email mailbox validation: domain=%s transport=%s provider=%s",
        domain,
        probe_transport,
        profile.provider.id,
    )
    try:
        async with asyncio.timeout(settings.validation_total_timeout_seconds):
            if settings.validation_probe_relay_host:
                mailbox = await validate_mailbox_via_tunnel(
                    normalized_email, sender_email, profile, control_probe_count
                )
            else:
                mailbox = await validate_mailbox(
                    domain,
                    dns_res.mx_records,
                    normalized_email,
                    sender_email,
                    profile,
                    control_probe_count,
                )
    except TimeoutError:
        logger.warning(
            "Email mailbox validation timed out: domain=%s transport=%s budget_seconds=%s",
            domain,
            probe_transport,
            settings.validation_total_timeout_seconds,
        )
        mailbox = EmailValidationMailbox(
            is_valid=None,
            transport=probe_transport,
            reason_code="smtp_probe_timeout",
            error=(
                "Mailbox validation exceeded the "
                f"{settings.validation_total_timeout_seconds:g}-second probe budget"
            ),
        )

    # 8. Calculate overall status
    is_valid = True
    status: Literal["valid", "invalid", "undetermined", "disposable", "catch_all"] = "valid"
    verdict: Literal["deliverable", "undeliverable", "risky", "unknown"] = "deliverable"
    deliverable: bool | None = True
    confidence = 0.95
    reason = mailbox.reason_code or "mailbox_accepted"

    if is_disposable:
        status = "disposable"
        is_valid = False
        verdict = "risky"
        deliverable = mailbox.is_valid
        confidence = 0.8
        reason = "disposable_domain"
    elif mailbox.is_valid is False:
        status = "invalid"
        is_valid = False
        verdict = "undeliverable"
        deliverable = False
        confidence = 0.98
    elif mailbox.catch_all is True:
        status = "catch_all"
        is_valid = True
        verdict = "risky"
        deliverable = None
        confidence = 0.5
        reason = "accept_all_domain"
    elif mailbox.is_valid is None:
        # If DNS is correct but SMTP connection is blocked/timed out, or greylisted
        status = "undetermined"
        is_valid = False
        verdict = "unknown"
        deliverable = None
        confidence = 0.2
        reason = mailbox.reason_code or "smtp_unknown"
    elif mailbox.selective_recipient_validation:
        # Every control was refused while the target was accepted, so the
        # destination looked this recipient up rather than accepting blindly.
        confidence = 0.97

    response = EmailValidationResponse(
        email=normalized_email,
        is_valid=is_valid,
        status=status,
        verdict=verdict,
        deliverable=deliverable,
        confidence=confidence,
        reason=reason,
        syntax=syntax,
        dns=dns_res,
        mailbox=mailbox,
        disposable=disposable,
        provider=_provider_schema(profile, domain_sig.inferred_backend if domain_sig else None),
        local_part=_local_part_schema(local_signals),
        domain_signals=_domain_signal_schema(domain_sig) if domain_sig else None,
    )

    return ValidationOutcome(
        response=response,
        profile=profile,
        probe=_probe_evidence(mailbox),
        local_part_delta=local_signals.risk_delta,
        local_part_notes=local_signals.notes,
        domain_signal_delta=domain_sig.risk_delta if domain_sig else 0.0,
        domain_signal_notes=domain_sig.notes if domain_sig else [],
    )


async def validate_email(email: str) -> EmailValidationResponse:
    """Validate email address syntax, DNS configuration, mailbox availability, and disposable status."""
    outcome = await validate_email_detailed(email)
    return outcome.response
