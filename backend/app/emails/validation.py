"""Email validation business logic.

Provides functions to validate email address syntax, verify DNS (MX/NS/A)
records, run SMTP RCPT TO handshake probes, and check against disposable domains.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from typing import Literal

import aiosmtplib
import dns.resolver

from app.config import settings
from app.emails.disposable import is_disposable_domain
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


def validate_syntax(email: str) -> EmailValidationSyntax:
    """Validate the syntax of an email address, rejecting reserved/internal domains."""
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

    if not EMAIL_REGEX.match(email):
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error="Invalid email address syntax",
        )

    # Check domain label lengths and hyphens
    domain_labels = domain.split(".")
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

    # Validate Punycode compatibility for IDNs
    try:
        domain.encode("idna").decode("ascii")
    except Exception as exc:
        return EmailValidationSyntax(
            is_valid=False,
            local_part=local_part,
            domain=domain,
            error=f"Invalid IDN punycode encoding: {exc}",
        )

    return EmailValidationSyntax(
        is_valid=True,
        local_part=local_part,
        domain=domain,
    )


async def validate_dns(domain: str) -> EmailValidationDns:
    """Verify NS, MX, and A records for a domain using custom cached resolver."""
    has_mx = False
    has_ns = False
    has_a = False
    mx_records: list[tuple[int, str]] = []
    ns_records: list[str] = []
    a_records: list[str] = []

    # IDNA encoding for domains
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except Exception:
        ascii_domain = domain

    async def resolve_mx() -> None:
        nonlocal has_mx, mx_records
        try:
            answers = await asyncio.to_thread(_resolver.resolve, ascii_domain, "MX")
            for rdata in answers:
                pref = getattr(rdata, "preference", 0)
                exchange = str(getattr(rdata, "exchange", "")).rstrip(".")
                if exchange:
                    mx_records.append((pref, exchange))
            mx_records.sort()
            has_mx = len(mx_records) > 0
        except Exception:
            pass

    async def resolve_ns() -> None:
        nonlocal has_ns, ns_records
        try:
            answers = await asyncio.to_thread(_resolver.resolve, ascii_domain, "NS")
            for rdata in answers:
                ns_host = str(rdata.target).rstrip(".")
                if ns_host:
                    ns_records.append(ns_host)
            has_ns = len(ns_records) > 0
        except Exception:
            pass

    async def resolve_a() -> None:
        nonlocal has_a, a_records
        try:
            answers = await asyncio.to_thread(_resolver.resolve, ascii_domain, "A")
            for rdata in answers:
                a_records.append(str(rdata.address))
            has_a = len(a_records) > 0
        except Exception:
            pass

    await asyncio.gather(resolve_mx(), resolve_ns(), resolve_a())

    # Overall DNS validity: needs name servers and (MX or A/AAAA fallback for delivery)
    is_valid = has_ns and (has_mx or has_a)

    formatted_mx = [f"{pref} {host}." for pref, host in mx_records]
    formatted_ns = [f"{host}." for host in ns_records]

    error = None
    if not is_valid:
        if not has_ns:
            error = "No Name Servers (NS) found; domain may not exist"
        elif not has_mx and not has_a:
            error = "No MX or A records found; domain cannot receive mail"

    return EmailValidationDns(
        is_valid=is_valid,
        has_mx=has_mx,
        has_ns=has_ns,
        has_a=has_a,
        mx_records=formatted_mx,
        ns_records=formatted_ns,
        a_records=a_records,
        error=error,
    )


async def validate_mailbox(
    domain: str,
    mx_records: list[str],
    target_email: str,
    sender_email: str,
) -> EmailValidationMailbox:
    """Connect to the MX server and run SMTP RCPT TO handshake probe, handling greylisting."""
    # Check if SMTP checks are enabled by setting configurations
    if not settings.validation_smtp_probe_enabled:
        return EmailValidationMailbox(
            is_valid=None,
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
    for host in hosts:
        try:
            smtp = aiosmtplib.SMTP(hostname=host, port=25, timeout=5.0)
            await smtp.connect()
            try:
                try:
                    await smtp.ehlo()
                except Exception:
                    with contextlib.suppress(Exception):
                        await smtp.helo()

                # Send MAIL FROM: system probe address or null sender fallback
                try:
                    code, msg = await smtp.mail(sender_email)
                    if code != 250:
                        code, msg = await smtp.mail("<>")
                except Exception:
                    code, msg = await smtp.mail("<>")

                # Send RCPT TO
                code, msg = await smtp.rcpt(target_email)

                # Check if it was greylisted (4xx temporary failure)
                if 400 <= code < 500:
                    await smtp.quit()
                    return EmailValidationMailbox(
                        is_valid=None,
                        smtp_code=code,
                        smtp_response=msg,
                        catch_all=False,
                        error=f"Greylisted or temporary SMTP failure: {msg}",
                    )

                # Check for catch-all domain status if the target mailbox is accepted
                catch_all = False
                if code in (250, 251):
                    random_mailbox = f"mailcue-catchall-probe-{int(time.time())}@{domain}"
                    try:
                        await smtp.rset()
                        try:
                            await smtp.mail(sender_email)
                        except Exception:
                            await smtp.mail("<>")

                        rand_code, _ = await smtp.rcpt(random_mailbox)
                        if rand_code in (250, 251):
                            catch_all = True
                    except Exception as catchall_exc:
                        logger.debug("Failed catch-all probe on host %s: %s", host, catchall_exc)

                await smtp.quit()
                return EmailValidationMailbox(
                    is_valid=code in (250, 251),
                    smtp_code=code,
                    smtp_response=msg,
                    catch_all=catch_all,
                )
            finally:
                if smtp.is_connected:
                    smtp.close()
        except aiosmtplib.SMTPResponseException as exc:
            # Handle temporary / greylisting codes raised as SMTPResponseException
            if exc.code is not None and 400 <= exc.code < 500:
                return EmailValidationMailbox(
                    is_valid=None,
                    smtp_code=exc.code,
                    smtp_response=exc.message,
                    catch_all=False,
                    error=f"Greylisted or temporary SMTP failure: {exc.message}",
                )
            # Mailbox explicitly rejected by host (5xx)
            return EmailValidationMailbox(
                is_valid=False,
                smtp_code=exc.code,
                smtp_response=exc.message,
                catch_all=False,
            )
        except Exception as exc:
            last_error = exc
            logger.debug("SMTP probe failed on host %s: %s", host, exc)

    return EmailValidationMailbox(
        is_valid=None,
        error=f"SMTP connection failed: {last_error or 'No hosts resolved'}",
    )


async def validate_email(email: str) -> EmailValidationResponse:
    """Validate email address syntax, DNS configuration, mailbox availability, and disposable status."""
    # 1. Syntax Check
    syntax = validate_syntax(email)
    if not syntax.is_valid or not syntax.domain:
        return EmailValidationResponse(
            email=email,
            is_valid=False,
            status="invalid",
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
    disposable = EmailValidationDisposable(is_disposable=is_disposable)

    # 3. DNS check
    dns_res = await validate_dns(domain)
    if not dns_res.is_valid:
        return EmailValidationResponse(
            email=email,
            is_valid=False,
            status="invalid",
            syntax=syntax,
            dns=dns_res,
            mailbox=EmailValidationMailbox(is_valid=None, error="DNS validation failed"),
            disposable=disposable,
        )

    # 4. Mailbox Check (SMTP probe)
    # Using a sender email belonging to mailcue system domain
    sender_email = f"validate-probe@{settings.domain}"
    mailbox = await validate_mailbox(domain, dns_res.mx_records, email, sender_email)

    # 5. Calculate overall status
    is_valid = True
    status: Literal["valid", "invalid", "undetermined", "disposable", "catch_all"] = "valid"

    if is_disposable:
        status = "disposable"
        is_valid = False
    elif mailbox.is_valid is False:
        status = "invalid"
        is_valid = False
    elif mailbox.catch_all is True:
        status = "catch_all"
        is_valid = True
    elif mailbox.is_valid is None:
        # If DNS is correct but SMTP connection is blocked/timed out, or greylisted
        status = "undetermined"
        is_valid = True  # Treat as valid if domain is correct and syntax is valid, but SMTP check is blocked/greylisted

    return EmailValidationResponse(
        email=email,
        is_valid=is_valid,
        status=status,
        syntax=syntax,
        dns=dns_res,
        mailbox=mailbox,
        disposable=disposable,
    )
