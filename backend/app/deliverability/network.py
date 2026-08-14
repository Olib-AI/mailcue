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
from app.emails.schemas import (
    DeliverabilityCategory,
    DeliverabilityCheck,
    DeliverabilityEvidence,
)

_HOST_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z",
    re.I,
)
_RESERVED_SUFFIXES = (".internal", ".invalid", ".local", ".localhost", ".test")


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


class _DnsWorker:
    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(settings.deliverability_network_concurrency)

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
                dns.resolver.NoNameservers,
                dns.resolver.LifetimeTimeout,
            ):
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


def _origin_ip(msg: EmailMessage) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    received = [str(value) for value in msg.get_all("Received", [])]
    if not received:
        return None
    # The receiving MTA prepends its own hop. Older Received fields are sender
    # controlled and cannot be trusted for reputation or blocklist queries.
    candidates = re.findall(r"\[([0-9a-f:.]+)\]", received[0], re.I)
    for candidate in reversed(candidates):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.is_global:
            return address
    return None


def _message_domains(msg: EmailMessage, sender_domain: str) -> list[str]:
    domains = [sender_domain]
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
    worker: _DnsWorker, domain: str, identities: list[tuple[str, str]]
) -> list[DeliverabilityCheck]:
    spf_task = worker.resolve(domain, "TXT")
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
    if len(spf) == 1:
        direct_lookup_terms, _nested = _spf_lookup_terms(spf[0])
        lookup_terms, lookup_incomplete = await _spf_recursive_lookups(
            worker, spf[0], visited={domain}
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
                recommendation="Publish exactly one valid SPF TXT policy.",
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
    worker: _DnsWorker, origin: ipaddress.IPv4Address | ipaddress.IPv6Address | None
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
    elif origin.version != 4:
        dnsbl = _check(
            "dnsbl",
            "reputation",
            "Configured blocklists",
            "info",
            "Configured IPv4 blocklists were not queried for an IPv6 origin.",
            points=0,
            max_points=0,
        )
    else:
        reversed_ip = ".".join(reversed(str(origin).split(".")))
        answers = await asyncio.gather(
            *(worker.resolve(f"{reversed_ip}.{zone}", "A") for zone in zones)
        )
        listed = [zone for zone, records in zip(zones, answers, strict=True) if records]
        dnsbl = _check(
            "dnsbl",
            "reputation",
            "Configured blocklists",
            "fail" if listed else "pass",
            "The origin IP is listed by a configured DNS blocklist."
            if listed
            else "The origin IP was not found on the configured DNS blocklists.",
            points=0 if listed else 5,
            max_points=5,
            details=[f"Checked zones: {len(zones)}"] + [f"Listed by: {zone}" for zone in listed],
            recommendation="Follow each list operator's evidence and delisting process."
            if listed
            else None,
        )
    return [reverse_check, dnsbl]


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
    answers = await asyncio.gather(
        *(worker.resolve(f"{domain}.{zone}", "A") for domain, zone in queries)
    )
    listed = [
        (domain, zone) for (domain, zone), records in zip(queries, answers, strict=True) if records
    ]
    return _check(
        "domain_dnsbl",
        "reputation",
        "Configured domain blocklists",
        "fail" if listed else "pass",
        "A sender or linked domain is listed by a configured domain blocklist."
        if listed
        else "No sender or linked domain was found on the configured domain blocklists.",
        points=0 if listed else 5,
        max_points=5,
        details=[
            f"Checked {len(queries)} bounded domain and zone combination(s).",
            *(f"Listed: {domain} by {zone}" for domain, zone in listed),
        ],
        recommendation="Review the listed domain and follow the list operator's evidence and removal process."
        if listed
        else None,
    )


async def _reputation_checks(
    worker: _DnsWorker,
    origin: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
    domains: list[str],
) -> list[DeliverabilityCheck]:
    ip_checks, domain_check = await asyncio.gather(
        _ip_reputation_checks(worker, origin),
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
    try:
        async with asyncio.timeout(settings.deliverability_network_timeout_seconds * 4):
            dns_checks, reputation_checks = await asyncio.gather(
                _domain_checks(worker, domain, _dkim_identities(parsed)),
                _reputation_checks(worker, _origin_ip(parsed), _message_domains(parsed, domain)),
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
