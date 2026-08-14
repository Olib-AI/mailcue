"""Bounded opt-in DNS and reputation enrichment for deliverability reports."""

from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import re
from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Literal
from urllib.parse import urlsplit

import dns.resolver
import dns.reversename
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from app.config import settings
from app.emails.deliverability import trusted_spf_domain
from app.emails.schemas import (
    DeliverabilityCategory,
    DeliverabilityCheck,
    DeliverabilityEvidence,
)

_HOST_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z",
    re.I,
)
_RESERVED_SUFFIXES = (
    ".example",
    ".internal",
    ".invalid",
    ".local",
    ".localhost",
    ".test",
)
_DNSBL_ERROR_NETWORK = ipaddress.ip_network("127.255.255.0/24")


def _check(
    check_id: str,
    category: Literal["dns", "reputation"],
    title: str,
    status: Literal["pass", "warning", "fail", "info"],
    summary: str,
    *,
    points: float,
    max_points: float,
    details: list[str] | None = None,
    evidence: list[DeliverabilityEvidence] | None = None,
    recommendation: str | None = None,
) -> DeliverabilityCheck:
    return DeliverabilityCheck(
        id=check_id,
        category=category,
        title=title,
        status=status,
        summary=summary,
        points=points,
        max_points=max_points,
        details=details or [],
        evidence=evidence or [],
        recommendation=recommendation,
    )


def _safe_domain(value: str | None) -> str | None:
    if not value:
        return None
    try:
        normalized = value.strip().rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if (
        not _HOST_RE.fullmatch(normalized)
        or normalized.endswith(_RESERVED_SUFFIXES)
        or len(normalized) > 253
    ):
        return None
    return normalized


def _join_txt(value: object) -> str:
    strings = getattr(value, "strings", None)
    if strings:
        return b"".join(strings).decode("utf-8", errors="replace")
    return str(value).strip().strip('"').replace('" "', "")


def _ip_dnsbl_prefix(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    if address.version == 4:
        return ".".join(reversed(str(address).split(".")))
    return ".".join(reversed(address.exploded.replace(":", "")))


def _dnsbl_answer(records: list[str]) -> tuple[bool, bool]:
    """Return listing and service-error flags without trusting arbitrary DNS A data."""
    listed = False
    service_error = False
    for record in records:
        try:
            address = ipaddress.ip_address(record)
        except ValueError:
            service_error = True
            continue
        if (
            not isinstance(address, ipaddress.IPv4Address)
            or not address.is_loopback
            or address in _DNSBL_ERROR_NETWORK
            or address.packed[-1] == 255
        ):
            service_error = True
        else:
            listed = True
    return listed, service_error


class _DnsWorker:
    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(settings.deliverability_network_concurrency)
        self.lookup_errors: set[tuple[str, str]] = set()

    async def resolve(self, name: str, record_type: str) -> list[str]:
        async with self._semaphore:
            try:
                answer = await asyncio.to_thread(
                    dns.resolver.resolve,
                    name,
                    record_type,
                    lifetime=settings.deliverability_network_timeout_seconds,
                    search=False,
                )
            except (
                dns.resolver.NXDOMAIN,
                dns.resolver.NoAnswer,
            ):
                return []
            except (
                dns.resolver.NoNameservers,
                dns.resolver.LifetimeTimeout,
            ):
                self.lookup_errors.add((name, record_type))
                return []
        if record_type == "TXT":
            return [_join_txt(item)[:4096] for item in answer][:50]
        return [str(item).rstrip(".")[:4096] for item in answer][:50]


def _spf_lookup_terms(record: str) -> tuple[int, list[str]]:
    count = 0
    nested: list[str] = []
    for raw_term in record.split()[1:]:
        term = raw_term.lstrip("+-~?")
        mechanism = term.split(":", 1)[0].split("=", 1)[0].lower()
        if mechanism in {"a", "mx", "ptr", "include", "exists", "redirect"}:
            count += 1
        if mechanism == "include" and ":" in term:
            nested.append(term.split(":", 1)[1])
        elif mechanism == "redirect" and "=" in term:
            nested.append(term.split("=", 1)[1])
    return count, nested


async def _spf_recursive_lookups(
    worker: _DnsWorker,
    record: str,
    *,
    visited: set[str],
    depth: int = 0,
) -> tuple[int, bool]:
    direct, nested_domains = _spf_lookup_terms(record)
    if depth >= 5:
        return direct, bool(nested_domains)
    total = direct
    incomplete = False
    for raw_domain in nested_domains[:10]:
        domain = _safe_domain(raw_domain)
        if domain is None or domain in visited:
            incomplete = True
            continue
        visited.add(domain)
        records = [
            value
            for value in await worker.resolve(domain, "TXT")
            if value.lower().startswith("v=spf1")
        ]
        if len(records) != 1:
            incomplete = True
            continue
        nested_count, nested_incomplete = await _spf_recursive_lookups(
            worker, records[0], visited=visited, depth=depth + 1
        )
        total += nested_count
        incomplete = incomplete or nested_incomplete
        if total > 10:
            break
    return total, incomplete


def _dkim_identities(msg: EmailMessage) -> list[tuple[str, str]]:
    identities: set[tuple[str, str]] = set()
    for value in msg.get_all("DKIM-Signature", []):
        selector = re.search(r"(?:^|;)\s*s=([a-z0-9._-]{1,63})(?:;|\s|$)", str(value), re.I)
        signing_domain = re.search(r"(?:^|;)\s*d=([a-z0-9.-]{1,253})(?:;|\s|$)", str(value), re.I)
        domain = _safe_domain(signing_domain.group(1) if signing_domain else None)
        if selector and domain:
            identities.add((selector.group(1).lower(), domain))
    auth = str((msg.get_all("Authentication-Results", []) or [""])[0])
    for segment in auth.split(";"):
        selector = re.search(r"\bheader\.s=([a-z0-9._-]{1,63})", segment, re.I)
        signing_domain = re.search(r"\bheader\.d=([a-z0-9.-]{1,253})", segment, re.I)
        domain = _safe_domain(signing_domain.group(1) if signing_domain else None)
        if selector and domain:
            identities.add((selector.group(1).lower(), domain))
    return sorted(identities)[:10]


def _dkim_key_description(record: str) -> tuple[bool, bool, str]:
    tags = {
        match.group(1).lower(): match.group(2).strip()
        for match in re.finditer(r"(?:^|;)\s*([a-z]+)\s*=\s*([^;]*)", record, re.I)
    }
    key_value = tags.get("p")
    if key_value is None:
        return False, False, "The DKIM record has no public-key tag."
    if not key_value:
        return False, False, "The DKIM key is revoked because its public-key tag is empty."
    try:
        decoded = base64.b64decode(key_value, validate=True)
        public_key = (
            ed25519.Ed25519PublicKey.from_public_bytes(decoded)
            if tags.get("k", "rsa").lower() == "ed25519"
            else serialization.load_der_public_key(decoded)
        )
    except (ValueError, TypeError, binascii.Error):
        return False, False, "The DKIM public key is malformed."
    if isinstance(public_key, rsa.RSAPublicKey):
        bits = public_key.key_size
        return True, bits < 2048, f"RSA public key size: {bits} bits."
    if isinstance(public_key, ed25519.Ed25519PublicKey):
        return True, False, "Ed25519 public key."
    return False, False, "The DKIM record uses an unsupported public-key type."


def _origin_route_identity(
    msg: EmailMessage,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address | None, str | None]:
    received = [str(value) for value in msg.get_all("Received", [])]
    if not received:
        return None, None
    # Dovecot LMTP and SpamAssassin loopback re-injection prepend local
    # Received fields. Skip only those exact leading handoffs, then trust the
    # first public handoff recorded by the receiving MTA. Never cross another
    # private or malformed boundary into older fields.
    for trusted_hop in received:
        lmtp = re.match(
            r"\s*from\s+([^\s(;]+).*?\s+by\s+([^\s(;]+).*?\s+with\s+LMTP\b",
            trusted_hop,
            re.I | re.S,
        )
        if lmtp:
            from_host = lmtp.group(1).strip("[]").lower().rstrip(".")
            by_host = lmtp.group(2).strip("[]").lower().rstrip(".")
            configured_host = settings.hostname.strip().lower().rstrip(".")
            if from_host == by_host == configured_host:
                continue
        from_clause = re.split(r"\s+by\s+", trusted_hop, maxsplit=1, flags=re.I)[0]
        explicit_greeting = re.search(
            r"\b(?:ehlo|helo)(?:\s*=|\s+)\s*[\"']?([a-z0-9._-]{1,253})",
            from_clause,
            re.I,
        )
        from_identity = re.match(r"\s*from\s+([^\s(;]+)", from_clause, re.I)
        greeting = _safe_domain(
            explicit_greeting.group(1)
            if explicit_greeting
            else from_identity.group(1).strip("[]")
            if from_identity
            else None
        )
        addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for candidate in reversed(re.findall(r"\[([0-9a-f:.]+)\]", from_clause, re.I)):
            try:
                addresses.append(ipaddress.ip_address(candidate))
            except ValueError:
                continue
        public = next((address for address in addresses if address.is_global), None)
        if public is not None:
            return public, greeting
        if addresses and all(address.is_loopback for address in addresses):
            continue
        return None, greeting
    return None, None


def _origin_ip(msg: EmailMessage) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    return _origin_route_identity(msg)[0]


def _message_domains(
    msg: EmailMessage, sender_domain: str, additional_domains: list[str]
) -> list[str]:
    domains = list(dict.fromkeys([sender_domain, *additional_domains]))[:20]
    for part in msg.walk():
        if (
            part.get_content_type() != "text/html"
            or part.get_content_disposition() == "attachment"
        ):
            continue
        try:
            body = str(part.get_content())[:2_000_000]
        except (LookupError, UnicodeError):
            continue
        for url in re.findall(r"https?://[^\s'\"<>]+", body, re.I):
            host = _safe_domain(urlsplit(url).hostname)
            if host and host not in domains:
                domains.append(host)
            if len(domains) >= 20:
                return domains
    return domains


def _category(
    category_id: Literal["dns", "reputation"], title: str, checks: list[DeliverabilityCheck]
) -> DeliverabilityCategory:
    points = sum(check.points for check in checks)
    maximum = sum(check.max_points for check in checks)
    return DeliverabilityCategory(
        id=category_id,
        title=title,
        score=round(points / maximum * 100) if maximum else None,
        points=round(points, 1),
        max_points=round(maximum, 1),
        checks=checks,
    )


async def _domain_checks(
    worker: _DnsWorker,
    domain: str,
    identities: list[tuple[str, str]],
    spf_domain: str | None,
) -> list[DeliverabilityCheck]:
    spf_task = worker.resolve(spf_domain, "TXT") if spf_domain else asyncio.sleep(0, result=[])
    dmarc_task = worker.resolve(f"_dmarc.{domain}", "TXT")
    mx_task = worker.resolve(domain, "MX")
    bimi_task = worker.resolve(f"default._bimi.{domain}", "TXT")
    sts_task = worker.resolve(f"_mta-sts.{domain}", "TXT")
    tlsrpt_task = worker.resolve(f"_smtp._tls.{domain}", "TXT")
    spf_txt, dmarc_txt, mx, bimi_txt, sts_txt, tlsrpt_txt = await asyncio.gather(
        spf_task, dmarc_task, mx_task, bimi_task, sts_task, tlsrpt_task
    )
    checks: list[DeliverabilityCheck] = []
    spf = [record for record in spf_txt if record.lower().startswith("v=spf1")]
    if spf_domain is None:
        checks.append(
            _check(
                "dns_spf",
                "dns",
                "Published SPF policy",
                "info",
                "No receiver-verified MAIL FROM or fallback HELO domain was available for a DNS lookup.",
                points=0,
                max_points=0,
            )
        )
    elif len(spf) == 1:
        direct_lookup_terms, _nested = _spf_lookup_terms(spf[0])
        lookup_terms, lookup_incomplete = await _spf_recursive_lookups(
            worker, spf[0], visited={spf_domain}
        )
        status: Literal["pass", "warning"] = (
            "pass" if lookup_terms <= 10 and not lookup_incomplete else "warning"
        )
        checks.append(
            _check(
                "dns_spf",
                "dns",
                "Published SPF policy",
                status,
                "One SPF policy is published and its bounded lookup expansion is valid."
                if status == "pass"
                else "The SPF lookup expansion exceeds the limit or could not be fully resolved.",
                points=5 if status == "pass" else 2,
                max_points=5,
                details=[
                    f"Receiver-verified SPF identity: {spf_domain}",
                    spf[0],
                    f"Direct lookup terms: {direct_lookup_terms}",
                    f"Bounded recursive lookup terms: {lookup_terms}",
                    f"Expansion complete: {'yes' if not lookup_incomplete else 'no'}",
                ],
                recommendation=None
                if status == "pass"
                else "Flatten or simplify SPF without broadening authorization.",
            )
        )
    else:
        checks.append(
            _check(
                "dns_spf",
                "dns",
                "Published SPF policy",
                "fail",
                "No SPF policy was found."
                if not spf
                else "Multiple SPF policies create a permanent error.",
                points=0,
                max_points=5,
                details=spf,
                recommendation=f"Publish exactly one valid SPF TXT policy for {spf_domain}.",
            )
        )

    dmarc = [record for record in dmarc_txt if record.upper().startswith("V=DMARC1")]
    if len(dmarc) == 1:
        policy_match = re.search(r"(?:^|;)\s*p\s*=\s*(none|quarantine|reject)", dmarc[0], re.I)
        pct_match = re.search(r"(?:^|;)\s*pct\s*=\s*(\d{1,3})", dmarc[0], re.I)
        policy_value = policy_match.group(1).lower() if policy_match else "missing"
        pct = min(int(pct_match.group(1)), 100) if pct_match else 100
        enforcing = policy_value in {"quarantine", "reject"} and pct == 100
        checks.append(
            _check(
                "dns_dmarc",
                "dns",
                "Published DMARC policy",
                "pass" if enforcing else "warning",
                "DMARC is fully enforced."
                if enforcing
                else "DMARC exists but is monitoring-only, partial, or incomplete.",
                points=6 if enforcing else 3,
                max_points=6,
                details=[dmarc[0], f"Policy: {policy_value}", f"Applied percentage: {pct}"],
                recommendation=None
                if enforcing
                else "Move toward p=quarantine or p=reject at pct=100 after reviewing reports.",
            )
        )
    else:
        checks.append(
            _check(
                "dns_dmarc",
                "dns",
                "Published DMARC policy",
                "fail",
                "No single valid DMARC policy was found.",
                points=0,
                max_points=6,
                details=dmarc,
                recommendation="Publish one DMARC record at _dmarc on the visible From domain.",
            )
        )

    dkim_records = await asyncio.gather(
        *(
            worker.resolve(f"{selector}._domainkey.{signing_domain}", "TXT")
            for selector, signing_domain in identities
        )
    )
    dkim_details: list[str] = []
    valid_selectors: list[str] = []
    weak_selectors: list[str] = []
    for (selector, signing_domain), records in zip(identities, dkim_records, strict=True):
        identity = f"{selector}@{signing_domain}"
        selector_valid = False
        for record in records:
            valid, weak, description = _dkim_key_description(record)
            dkim_details.append(f"{identity}: {description}")
            if valid:
                selector_valid = True
                if weak:
                    weak_selectors.append(identity)
                break
        if selector_valid:
            valid_selectors.append(identity)
    if not identities:
        dkim_status: Literal["info", "pass", "warning", "fail"] = "info"
        dkim_points = dkim_max = 0
        dkim_summary = "No safe DKIM selector was available for a DNS lookup."
    elif valid_selectors:
        dkim_status = "warning" if weak_selectors else "pass"
        dkim_points, dkim_max = (3 if weak_selectors else 5), 5
        dkim_summary = (
            "A public DKIM key was found, but an observed RSA key is below 2048 bits."
            if weak_selectors
            else "A valid public DKIM key was found for the observed selector."
        )
    else:
        dkim_status, dkim_points, dkim_max = "fail", 0, 5
        dkim_summary = "No public DKIM key was found for the observed selector."
    checks.append(
        _check(
            "dns_dkim",
            "dns",
            "Published DKIM key",
            dkim_status,
            dkim_summary,
            points=dkim_points,
            max_points=dkim_max,
            details=(
                [
                    "Observed selector identities: "
                    + ", ".join(
                        f"{selector}@{signing_domain}" for selector, signing_domain in identities
                    ),
                    *dkim_details,
                ]
                if identities
                else []
            ),
            recommendation=(
                "Rotate RSA DKIM keys to at least 2048 bits."
                if weak_selectors
                else "Publish a valid selector key and keep it available while signed mail is in transit."
                if identities and not valid_selectors
                else None
            ),
        )
    )
    checks.append(
        _check(
            "dns_mx",
            "dns",
            "Domain mail routing",
            "pass" if mx else "warning",
            "The From domain publishes MX routing."
            if mx
            else "The From domain has no MX record. This can weaken identity credibility.",
            points=2 if mx else 1,
            max_points=2,
            details=mx,
        )
    )
    optional_records = (
        ("dns_bimi", "BIMI", bimi_txt, "v=BIMI1"),
        ("dns_mta_sts", "MTA-STS signaling", sts_txt, "v=STSv1"),
        ("dns_tls_rpt", "TLS reporting", tlsrpt_txt, "v=TLSRPTv1"),
    )
    for check_id, title, records, prefix in optional_records:
        found = next(
            (record for record in records if record.lower().startswith(prefix.lower())), None
        )
        checks.append(
            _check(
                check_id,
                "dns",
                title,
                "pass" if found else "info",
                f"A {title} record is published."
                if found
                else f"No {title} record was found. This feature is optional.",
                points=1 if found else 0,
                max_points=1 if found else 0,
                details=[found] if found else [],
            )
        )
    return checks


async def _ip_reputation_checks(
    worker: _DnsWorker,
    origin: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
    greeting: str | None,
) -> list[DeliverabilityCheck]:
    if origin is None:
        return [
            _check(
                "reverse_dns",
                "reputation",
                "Sending IP identity",
                "info",
                "No globally routable origin IP was available in the trusted route evidence.",
                points=0,
                max_points=0,
            ),
            _check(
                "smtp_identity",
                "reputation",
                "SMTP greeting identity",
                "info",
                "No globally routable origin IP was available for SMTP identity checks.",
                points=0,
                max_points=0,
            ),
            _check(
                "helo_spf",
                "reputation",
                "Published HELO SPF policy",
                "info",
                "No trusted public SMTP greeting identity was available for an SPF lookup.",
                points=0,
                max_points=0,
            ),
            _check(
                "dnsbl",
                "reputation",
                "Configured blocklists",
                "info",
                "Blocklist checks were not run without a public origin IP.",
                points=0,
                max_points=0,
            ),
        ]

    reverse_name = str(dns.reversename.from_address(str(origin))).rstrip(".")
    pointers = await worker.resolve(reverse_name, "PTR")
    forward: list[str] = []
    for pointer in pointers[:5]:
        forward.extend(await worker.resolve(pointer, "A" if origin.version == 4 else "AAAA"))
    confirmed = str(origin) in forward
    reverse_check = _check(
        "reverse_dns",
        "reputation",
        "Forward-confirmed reverse DNS",
        "pass" if confirmed else "fail",
        "The origin IP has forward-confirmed reverse DNS."
        if confirmed
        else "The origin IP does not have forward-confirmed reverse DNS.",
        points=5 if confirmed else 0,
        max_points=5,
        details=[f"Origin IP: {origin}"] + [f"PTR: {pointer}" for pointer in pointers],
        recommendation=None
        if confirmed
        else "Configure a stable PTR hostname whose A or AAAA record resolves back to the sending IP.",
    )

    if greeting is None:
        identity_check = _check(
            "smtp_identity",
            "reputation",
            "SMTP greeting identity",
            "warning",
            "The receiver-added delivery hop did not contain a valid public HELO or EHLO hostname.",
            points=0,
            max_points=5,
            details=[f"Origin IP: {origin}", *[f"PTR: {pointer}" for pointer in pointers]],
            recommendation="Use a stable public FQDN in HELO or EHLO that resolves to the sending IP.",
        )
        helo_spf = _check(
            "helo_spf",
            "reputation",
            "Published HELO SPF policy",
            "info",
            "No valid public HELO or EHLO hostname was available for an SPF lookup.",
            points=0,
            max_points=0,
        )
    else:
        greeting_a, greeting_aaaa, greeting_txt = await asyncio.gather(
            worker.resolve(greeting, "A"),
            worker.resolve(greeting, "AAAA"),
            worker.resolve(greeting, "TXT"),
        )
        greeting_addresses = [*greeting_a, *greeting_aaaa]
        address_matches = str(origin) in greeting_addresses
        ptr_matches = greeting in {pointer.lower().rstrip(".") for pointer in pointers}
        if address_matches and ptr_matches:
            identity_status: Literal["pass", "warning", "fail"] = "pass"
            identity_summary = (
                "The observed SMTP greeting, origin IP, forward DNS, and PTR are consistent."
            )
            identity_points = 5
            identity_recommendation = None
        elif address_matches:
            identity_status = "warning"
            identity_summary = "The SMTP greeting resolves to the origin IP, but it does not match the PTR hostname."
            identity_points = 3
            identity_recommendation = (
                "Align the sending IP PTR hostname with the HELO or EHLO hostname."
            )
        else:
            identity_status = "fail"
            identity_summary = "The observed SMTP greeting does not resolve to the sending IP."
            identity_points = 0
            identity_recommendation = (
                "Publish matching A or AAAA records and use that hostname in HELO or EHLO."
            )
        identity_check = _check(
            "smtp_identity",
            "reputation",
            "SMTP greeting identity",
            identity_status,
            identity_summary,
            points=identity_points,
            max_points=5,
            details=[
                f"Origin IP: {origin}",
                f"Observed HELO/EHLO: {greeting}",
                *[f"Greeting address: {address}" for address in greeting_addresses],
                *[f"PTR: {pointer}" for pointer in pointers],
            ],
            recommendation=identity_recommendation,
        )

        helo_records = [record for record in greeting_txt if record.lower().startswith("v=spf1")]
        if len(helo_records) == 1:
            lookup_terms, lookup_incomplete = await _spf_recursive_lookups(
                worker, helo_records[0], visited={greeting}
            )
            helo_valid = lookup_terms <= 10 and not lookup_incomplete
            helo_spf = _check(
                "helo_spf",
                "reputation",
                "Published HELO SPF policy",
                "pass" if helo_valid else "warning",
                "The SMTP greeting hostname publishes a bounded SPF policy."
                if helo_valid
                else "The HELO SPF lookup expansion exceeds the limit or is incomplete.",
                points=2 if helo_valid else 0,
                max_points=2,
                details=[
                    helo_records[0],
                    f"Bounded recursive lookup terms: {lookup_terms}",
                    f"Expansion complete: {'yes' if not lookup_incomplete else 'no'}",
                ],
                recommendation=None
                if helo_valid
                else "Simplify the SPF policy published on the HELO or EHLO hostname.",
            )
        else:
            helo_spf = _check(
                "helo_spf",
                "reputation",
                "Published HELO SPF policy",
                "warning" if not helo_records else "fail",
                "The SMTP greeting hostname does not publish an SPF policy."
                if not helo_records
                else "The SMTP greeting hostname publishes multiple SPF policies.",
                points=0,
                max_points=2,
                details=helo_records,
                recommendation="Publish exactly one SPF policy for the HELO or EHLO hostname.",
            )

    zones = [zone.strip().rstrip(".").lower() for zone in settings.deliverability_dnsbl_zones]
    if not zones:
        dnsbl = _check(
            "dnsbl",
            "reputation",
            "Configured blocklists",
            "info",
            "No DNS blocklist zones are configured, so no listing claim is made.",
            points=0,
            max_points=0,
        )
    else:
        reversed_ip = _ip_dnsbl_prefix(origin)
        query_names = [f"{reversed_ip}.{zone}" for zone in zones]
        answers = await asyncio.gather(*(worker.resolve(name, "A") for name in query_names))
        lookup_errors: set[tuple[str, str]] = getattr(worker, "lookup_errors", set())
        results = [
            (listed, invalid or (name, "A") in lookup_errors)
            for name, records in zip(query_names, answers, strict=True)
            for listed, invalid in [_dnsbl_answer(records)]
        ]
        listed = [index for index, result in enumerate(results, start=1) if result[0]]
        errors = [index for index, result in enumerate(results, start=1) if result[1]]
        dnsbl = _check(
            "dnsbl",
            "reputation",
            "Configured blocklists",
            "fail" if listed else "info" if errors else "pass",
            "The origin IP is listed by a configured DNS blocklist."
            if listed
            else "One or more blocklist queries returned an invalid or service-error response."
            if errors
            else "The origin IP was not found on the configured DNS blocklists.",
            points=0 if listed or errors else 5,
            max_points=5 if not errors or listed else 0,
            details=[
                f"Checked configured zones: {len(zones)}",
                *(f"Listed by configured IP blocklist {index}." for index in listed),
                *(f"Query error from configured IP blocklist {index}." for index in errors),
            ],
            recommendation="Follow each list operator's evidence and delisting process."
            if listed
            else "Check the blocklist account, query limits, and recursive DNS resolver."
            if errors
            else None,
        )
    return [reverse_check, identity_check, helo_spf, dnsbl]


async def _domain_blocklist_check(worker: _DnsWorker, domains: list[str]) -> DeliverabilityCheck:
    zones = settings.deliverability_domain_dnsbl_zones
    if not zones:
        return _check(
            "domain_dnsbl",
            "reputation",
            "Configured domain blocklists",
            "info",
            "No domain blocklist zones are configured, so no domain listing claim is made.",
            points=0,
            max_points=0,
        )
    queries = [(domain, zone) for domain in domains[:20] for zone in zones][:100]
    query_names = [f"{domain}.{zone}" for domain, zone in queries]
    answers = await asyncio.gather(*(worker.resolve(name, "A") for name in query_names))
    lookup_errors: set[tuple[str, str]] = getattr(worker, "lookup_errors", set())
    results = [
        (listed, invalid or (name, "A") in lookup_errors)
        for name, records in zip(query_names, answers, strict=True)
        for listed, invalid in [_dnsbl_answer(records)]
    ]
    zone_indexes = {zone: index for index, zone in enumerate(zones, start=1)}
    listed = [
        (domain, zone_indexes[zone])
        for (domain, zone), result in zip(queries, results, strict=True)
        if result[0]
    ]
    errors = [
        (domain, zone_indexes[zone])
        for (domain, zone), result in zip(queries, results, strict=True)
        if result[1]
    ]
    return _check(
        "domain_dnsbl",
        "reputation",
        "Configured domain blocklists",
        "fail" if listed else "info" if errors else "pass",
        "A sender or linked domain is listed by a configured domain blocklist."
        if listed
        else "One or more domain blocklist queries returned an invalid or service-error response."
        if errors
        else "No tested sender, signing, or linked domain was listed by the configured domain blocklists.",
        points=0 if listed or errors else 5,
        max_points=5 if not errors or listed else 0,
        details=[
            f"Checked {len(queries)} bounded domain and zone combination(s).",
            *(
                f"Listed: {domain} by configured domain blocklist {index}."
                for domain, index in listed
            ),
            *(
                f"Query error: {domain} through configured domain blocklist {index}."
                for domain, index in errors
            ),
        ],
        recommendation="Review the listed domain and follow the list operator's evidence and removal process."
        if listed
        else "Check the blocklist account, query limits, and recursive DNS resolver."
        if errors
        else None,
    )


async def _reputation_checks(
    worker: _DnsWorker,
    origin: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
    greeting: str | None,
    domains: list[str],
) -> list[DeliverabilityCheck]:
    ip_checks, domain_check = await asyncio.gather(
        _ip_reputation_checks(worker, origin, greeting),
        _domain_blocklist_check(worker, domains),
    )
    return [*ip_checks, domain_check]


async def analyze_network(
    raw: bytes, *, sender_domain: str | None
) -> list[DeliverabilityCategory]:
    """Run only configured DNS checks under a strict overall wall-clock budget."""
    domain = _safe_domain(sender_domain)
    if domain is None:
        return [
            _category(
                "dns",
                "DNS and domain policy",
                [
                    _check(
                        "dns_domain",
                        "dns",
                        "Public sender domain",
                        "info",
                        "The sender domain is absent, invalid, or reserved, so public DNS was not queried.",
                        points=0,
                        max_points=0,
                    )
                ],
            )
        ]
    parsed = message_from_bytes(raw, policy=policy.default)
    if not isinstance(parsed, EmailMessage):
        return []
    worker = _DnsWorker()
    origin, greeting = _origin_route_identity(parsed)
    spf_domain = _safe_domain(trusted_spf_domain(parsed))
    dkim_identities = _dkim_identities(parsed)
    reputation_domains = _message_domains(
        parsed,
        domain,
        [
            value
            for value in [spf_domain, *(signing_domain for _, signing_domain in dkim_identities)]
            if value is not None
        ],
    )
    try:
        async with asyncio.timeout(settings.deliverability_network_timeout_seconds * 4):
            dns_checks, reputation_checks = await asyncio.gather(
                _domain_checks(worker, domain, dkim_identities, spf_domain),
                _reputation_checks(
                    worker,
                    origin,
                    greeting,
                    reputation_domains,
                ),
            )
    except TimeoutError:
        timeout_check = _check(
            "network_timeout",
            "dns",
            "Network check budget",
            "info",
            "Network enrichment exceeded its bounded time budget.",
            points=0,
            max_points=0,
        )
        return [_category("dns", "DNS and domain policy", [timeout_check])]
    return [
        _category("dns", "DNS and domain policy", dns_checks),
        _category("reputation", "IP reputation", reputation_checks),
    ]
