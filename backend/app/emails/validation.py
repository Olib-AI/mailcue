"""Email validation business logic.

Provides functions to validate email address syntax, verify DNS (MX/NS/A)
records, run SMTP RCPT TO handshake probes, and check against disposable domains.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import re
import socket
import uuid
from typing import Literal

import aiosmtplib
import dns.resolver

from app.config import settings
from app.emails.disposable import is_disposable_domain, is_forwarding_alias_domain
from app.emails.schemas import (
    EmailValidationDisposable,
    EmailValidationDns,
    EmailValidationMailbox,
    EmailValidationResponse,
    EmailValidationSyntax,
)

logger = logging.getLogger("mailcue.validation")

# Robust email regex according to RFCs (allowing standard characters)
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)

ENHANCED_STATUS_REGEX = re.compile(r"\b([245])\.(\d{1,3})\.(\d{1,3})\b")

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

# Configure a shared DNS resolver with 1.0s query timeout, 2.0s lifetime, and cache
_resolver = dns.resolver.Resolver()
_resolver.timeout = 1.0
_resolver.lifetime = 2.0
_resolver.cache = dns.resolver.LRUCache()


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


async def validate_mailbox(
    domain: str,
    mx_records: list[str],
    target_email: str,
    sender_email: str,
) -> EmailValidationMailbox:
    """Run a direct, non-delivery SMTP envelope probe against destination MXs."""
    # Check if SMTP checks are enabled by setting configurations
    if not settings.validation_smtp_probe_enabled:
        return EmailValidationMailbox(
            is_valid=None,
            transport="none",
            reason_code="smtp_probe_disabled",
            error="SMTP probe disabled by configuration",
        )

    hosts: list[str] = []
    if mx_records:
        for mx in mx_records:
            parts = mx.split()
            if len(parts) == 2:
                hosts.append(parts[1].rstrip("."))
            else:
                hosts.append(mx.rstrip("."))
    else:
        # Fall back to domain itself if no MX records
        hosts.append(domain)

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

                    sender_ok = False
                    for sender in (sender_email, ""):
                        try:
                            code, _ = await smtp.mail(sender)
                            if 200 <= code < 300:
                                sender_ok = True
                                break
                            with contextlib.suppress(Exception):
                                await smtp.rset()
                        except aiosmtplib.SMTPResponseException:
                            with contextlib.suppress(Exception):
                                await smtp.rset()
                    if not sender_ok:
                        last_error = "Destination rejected the probe envelope sender"
                        continue

                    try:
                        code, msg = await smtp.rcpt(target_email)
                    except aiosmtplib.SMTPResponseException as exc:
                        code, msg = int(exc.code or 0), exc.message
                    msg_text = _smtp_text(msg)

                    if 400 <= code < 500:
                        last_inconclusive = EmailValidationMailbox(
                            is_valid=None,
                            smtp_code=code,
                            smtp_response=msg_text,
                            catch_all=None,
                            transport="direct",
                            reason_code="smtp_temporary_failure",
                            error=f"Temporary SMTP failure: {msg_text}",
                        )
                        continue

                    if code not in (250, 251):
                        if _is_mailbox_rejection(code, msg_text):
                            return EmailValidationMailbox(
                                is_valid=False,
                                smtp_code=code,
                                smtp_response=msg_text,
                                catch_all=False,
                                transport="direct",
                                reason_code="mailbox_rejected",
                            )
                        last_inconclusive = EmailValidationMailbox(
                            is_valid=None,
                            smtp_code=code,
                            smtp_response=msg_text,
                            catch_all=None,
                            transport="direct",
                            reason_code="smtp_policy_rejection",
                            error="SMTP policy rejection did not prove that the mailbox is absent",
                        )
                        continue

                    catch_all: bool | None = None
                    random_mailbox = f"mailcue-probe-{uuid.uuid4().hex}@{domain}"
                    try:
                        await smtp.rset()
                        for sender in (sender_email, ""):
                            try:
                                sender_code, _ = await smtp.mail(sender)
                                if 200 <= sender_code < 300:
                                    rand_code, _ = await smtp.rcpt(random_mailbox)
                                    catch_all = rand_code in (250, 251)
                                    break
                            except aiosmtplib.SMTPResponseException:
                                with contextlib.suppress(Exception):
                                    await smtp.rset()
                    except Exception as catchall_exc:
                        logger.debug("Failed catch-all probe on host %s: %s", host, catchall_exc)

                    return EmailValidationMailbox(
                        is_valid=True,
                        smtp_code=code,
                        smtp_response=msg_text,
                        catch_all=catch_all,
                        transport="direct",
                        reason_code="mailbox_accepted",
                    )
                except Exception as exc:
                    last_error = str(exc)
                    if isinstance(exc, aiosmtplib.SMTPResponseException):
                        last_inconclusive = EmailValidationMailbox(
                            is_valid=None,
                            smtp_code=exc.code,
                            smtp_response=_smtp_text(exc.message),
                            catch_all=None,
                            transport="direct",
                            reason_code="smtp_session_rejected",
                            error="SMTP session was rejected before recipient validation",
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


def _is_mailbox_rejection(code: int, message: str) -> bool:
    """Return true only for recipient-stage evidence that the address is absent."""
    if not 500 <= code < 600:
        return False
    enhanced = ENHANCED_STATUS_REGEX.search(message)
    if enhanced:
        return (
            enhanced.group(1) == "5"
            and enhanced.group(2) == "1"
            and enhanced.group(3)
            in {
                "0",
                "1",
                "3",
                "6",
            }
        )
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "no such user",
            "user unknown",
            "unknown recipient",
            "recipient not found",
            "mailbox does not exist",
            "invalid recipient",
        )
    )


async def validate_mailbox_via_tunnel(
    target_email: str,
    sender_email: str,
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
    try:
        await smtp.connect()
        await smtp.ehlo()
        code, message = await smtp.execute_command(
            b"XMAILCUEPROBE",
            target_email.encode("utf-8"),
            sender_email.encode("utf-8"),
            timeout=max(
                settings.validation_smtp_timeout_seconds,
                settings.validation_total_timeout_seconds - 3,
            ),
        )
        text = _smtp_text(message)
        match = re.search(r"upstream_code=(\d{3})", text)
        upstream_code = int(match.group(1)) if match else None
        if code == 250:
            return EmailValidationMailbox(
                is_valid=True,
                smtp_code=upstream_code,
                smtp_response=text,
                catch_all=False,
                transport="mailcue_tunnel",
                reason_code="mailbox_accepted",
            )
        if code == 252:
            return EmailValidationMailbox(
                is_valid=True,
                smtp_code=upstream_code,
                smtp_response=text,
                catch_all=True,
                transport="mailcue_tunnel",
                reason_code="accept_all_domain",
            )
        if code == 550:
            return EmailValidationMailbox(
                is_valid=False,
                smtp_code=upstream_code,
                smtp_response=text,
                catch_all=False,
                transport="mailcue_tunnel",
                reason_code="mailbox_rejected",
            )
        return EmailValidationMailbox(
            is_valid=None,
            smtp_code=upstream_code,
            smtp_response=text,
            catch_all=None,
            transport="mailcue_tunnel",
            reason_code="smtp_temporary_failure",
            error=text,
        )
    except Exception as exc:
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


async def validate_email(email: str) -> EmailValidationResponse:
    """Validate email address syntax, DNS configuration, mailbox availability, and disposable status."""
    # 1. Syntax Check
    normalized_email = email.strip()
    syntax = validate_syntax(normalized_email)
    if not syntax.is_valid or not syntax.domain:
        return EmailValidationResponse(
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

    domain = syntax.domain

    # 2. Disposable check (Fast offline check)
    is_disposable = is_disposable_domain(domain)
    disposable = EmailValidationDisposable(
        is_disposable=is_disposable,
        is_forwarding_alias=is_forwarding_alias_domain(domain),
    )

    # 3. DNS check
    dns_res = await validate_dns(domain)
    if not dns_res.is_valid:
        return EmailValidationResponse(
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
        )

    # 4. Mailbox check. A configured tunnel is the authoritative path for a
    # deployment whose host cannot reach destination MX servers on port 25;
    # trying every direct MX/IP first can exceed the caller's request timeout.
    # The total budget also bounds multi-address direct probes.
    sender_email = f"validate-probe@{settings.domain}"
    try:
        async with asyncio.timeout(settings.validation_total_timeout_seconds):
            if settings.validation_probe_relay_host:
                mailbox = await validate_mailbox_via_tunnel(normalized_email, sender_email)
            else:
                mailbox = await validate_mailbox(
                    domain,
                    dns_res.mx_records,
                    normalized_email,
                    sender_email,
                )
    except TimeoutError:
        mailbox = EmailValidationMailbox(
            is_valid=None,
            transport=("mailcue_tunnel" if settings.validation_probe_relay_host else "direct"),
            reason_code="smtp_probe_timeout",
            error=(
                "Mailbox validation exceeded the "
                f"{settings.validation_total_timeout_seconds:g}-second probe budget"
            ),
        )

    # 5. Calculate overall status
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

    return EmailValidationResponse(
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
    )
