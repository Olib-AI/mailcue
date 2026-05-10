"""Domain management business logic — DKIM generation, DNS validation, config management."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import dns.resolver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domains.models import Domain
from app.domains.schemas import DnsCheckResponse, DnsRecordInfo, DomainDnsStateResponse
from app.tunnels.models import Tunnel

logger = logging.getLogger("mailcue.domains")

_config_lock = asyncio.Lock()


# ── DKIM key generation ──────────────────────────────────────────


async def _generate_dkim_keys(domain_name: str, selector: str) -> tuple[str, str | None]:
    """Generate DKIM keys using opendkim-genkey.

    Returns (private_key_path, public_key_txt).
    """
    key_dir = Path(f"/etc/opendkim/keys/{domain_name}")

    def _generate() -> tuple[str, str | None]:
        key_dir.mkdir(parents=True, exist_ok=True)

        subprocess.run(
            [
                "opendkim-genkey",
                "-b",
                "2048",
                "-h",
                "sha256",
                "-d",
                domain_name,
                "-s",
                selector,
                "-D",
                str(key_dir),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        private_key_path = str(key_dir / f"{selector}.private")
        txt_file = key_dir / f"{selector}.txt"

        public_key_txt: str | None = None
        if txt_file.exists():
            raw = txt_file.read_text()
            # opendkim-genkey emits zone-file syntax with the value split
            # across multiple ``<character-string>``s, e.g.:
            #   mail._domainkey IN TXT ( "v=DKIM1; h=sha256; k=rsa; "
            #                            "p=MIIB...JCV79b"
            #                            "jABGCrQtb...AQAB" ) ; comment
            # RFC 6376 §3.6.2.2 requires verifiers to concatenate the
            # strings with NO separator — the DNS resolver returns
            # ``...JCV79bjABGCrQtb...`` not ``...JCV79b jABGCrQtb...``.
            # We must do the same when storing the canonical form.
            public_key_txt = _parse_zonefile_txt(raw)

        # Fix ownership for OpenDKIM
        for path in key_dir.iterdir():
            with contextlib.suppress(FileNotFoundError):
                subprocess.run(
                    ["chown", "opendkim:opendkim", str(path)],
                    check=False,
                    capture_output=True,
                )

        return private_key_path, public_key_txt

    return await asyncio.to_thread(_generate)


# ── DNS validation ───────────────────────────────────────────────


def _join_txt_rdata(rdata: object) -> str:
    """Concatenate the ``<character-string>``s of a TXT rdata without a separator.

    DNS TXT records are wire-encoded as one-or-more 255-byte
    ``<character-string>``s (RFC 1035 §3.3.14).  Authentication semantics
    (SPF RFC 7208 §3.3, DKIM RFC 6376 §3.6.2.2) require the verifier to
    concatenate them *without* any whitespace, so a stray space inserted by
    ``str(rdata)`` would corrupt the value (e.g. break a base64 ``p=`` tag).
    Falls back to ``str()`` if the rdata is not a TXT-shaped object.
    """
    strings = getattr(rdata, "strings", None)
    if strings is None:
        return str(rdata).strip('"')
    parts: list[str] = []
    for chunk in strings:
        if isinstance(chunk, bytes | bytearray):
            parts.append(bytes(chunk).decode("utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


_ZONEFILE_TXT_RE = re.compile(r'"([^"]*)"')


def _parse_zonefile_txt(raw: str) -> str:
    """Extract a single canonical TXT value from a BIND zone-file fragment.

    Concatenates every ``"..."`` ``<character-string>`` with NO separator,
    matching how DNS resolvers join multi-string TXT records (RFC 1035
    §3.3.14, RFC 6376 §3.6.2.2).  Any text outside the quoted strings —
    record header, parentheses, comments, whitespace between strings — is
    discarded.
    """
    chunks = _ZONEFILE_TXT_RE.findall(raw)
    return "".join(chunks).strip()


def _normalize_dkim_txt(txt: str | None) -> str | None:
    """Strip whitespace from inside a DKIM ``p=`` base64 blob.

    Handles legacy DB rows that stored the value with a stray space at the
    chunk boundary inserted by the previous ``replace('"', "") + split()``
    parser.  Base64 has no whitespace, so any space inside ``p=`` was
    spurious and would never match what the resolver returns.
    """
    if txt is None:
        return None
    head, sep, tail = txt.partition("p=")
    if not sep:
        return txt
    return f"{head}p={''.join(tail.split())}"


def _format_mx_rdata(rdata: object) -> str:
    """Render an MX rdata as ``"<pref> <host>."`` to match ``expected_value``."""
    pref = getattr(rdata, "preference", None)
    exchange = getattr(rdata, "exchange", None)
    host = str(exchange).rstrip(".") if exchange is not None else ""
    if pref is None:
        return f"{host}."
    return f"{int(pref)} {host}."


async def _check_mx(domain_name: str, hostname: str) -> tuple[bool, str | None]:
    """Check if MX record points to our hostname.

    Returns ``(verified, current_value)`` where ``current_value`` is the
    full ``"<preference> <host>."`` form so the drift comparison can match
    the canonical ``expected_value`` exactly.
    """
    try:
        answers = await asyncio.to_thread(dns.resolver.resolve, domain_name, "MX")
        first_formatted: str | None = None
        for rdata in answers:
            formatted = _format_mx_rdata(rdata)
            if first_formatted is None:
                first_formatted = formatted
            mx_host = str(getattr(rdata, "exchange", "")).rstrip(".")
            if mx_host == hostname:
                return True, formatted
        return False, first_formatted
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False, None
    except Exception as exc:
        logger.debug("MX check for %s failed: %s", domain_name, exc)
        return False, None


async def _check_spf(domain_name: str) -> tuple[bool, str | None]:
    """Check if TXT record contains a valid SPF record."""
    try:
        answers = await asyncio.to_thread(dns.resolver.resolve, domain_name, "TXT")
        first_txt: str | None = None
        for rdata in answers:
            txt = _join_txt_rdata(rdata)
            if first_txt is None:
                first_txt = txt
            if txt.startswith("v=spf1"):
                return True, txt
        return False, first_txt
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False, None
    except Exception as exc:
        logger.debug("SPF check for %s failed: %s", domain_name, exc)
        return False, None


async def _check_dkim(
    domain_name: str, selector: str, expected_public_key: str | None
) -> tuple[bool, str | None]:
    """Check if DKIM TXT record is configured correctly."""
    dkim_domain = f"{selector}._domainkey.{domain_name}"
    try:
        answers = await asyncio.to_thread(dns.resolver.resolve, dkim_domain, "TXT")
        first_txt: str | None = None
        for rdata in answers:
            txt = _join_txt_rdata(rdata)
            if first_txt is None:
                first_txt = txt
            if "p=" in txt:
                # If we have an expected key, only treat as verified on exact
                # match.  Otherwise (no expected key recorded yet) accept any
                # ``p=``-bearing record.  Compare normalised forms so a
                # whitespace-corrupted legacy DB row still verifies against
                # a correctly-resolved DNS answer.
                if expected_public_key is None or _normalize_dkim_txt(txt) == _normalize_dkim_txt(
                    expected_public_key
                ):
                    return True, txt
                return False, txt
        return False, first_txt
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False, None
    except Exception as exc:
        logger.debug("DKIM check for %s failed: %s", dkim_domain, exc)
        return False, None


async def _check_dmarc(domain_name: str) -> tuple[bool, str | None]:
    """Check if DMARC TXT record exists."""
    dmarc_domain = f"_dmarc.{domain_name}"
    try:
        answers = await asyncio.to_thread(dns.resolver.resolve, dmarc_domain, "TXT")
        first_txt: str | None = None
        for rdata in answers:
            txt = _join_txt_rdata(rdata)
            if first_txt is None:
                first_txt = txt
            if txt.startswith("v=DMARC1"):
                return True, txt
        return False, first_txt
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False, None
    except Exception as exc:
        logger.debug("DMARC check for %s failed: %s", dmarc_domain, exc)
        return False, None


async def _check_helo_spf(hostname: str) -> tuple[bool, str | None]:
    """Check if the mail server hostname has its own SPF TXT record."""
    try:
        answers = await asyncio.to_thread(dns.resolver.resolve, hostname, "TXT")
        first_txt: str | None = None
        for rdata in answers:
            txt = _join_txt_rdata(rdata)
            if first_txt is None:
                first_txt = txt
            if txt.startswith("v=spf1"):
                return True, txt
        return False, first_txt
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False, None
    except Exception as exc:
        logger.debug("HELO SPF check for %s failed: %s", hostname, exc)
        return False, None


async def _check_bimi(domain_name: str) -> tuple[bool, str | None]:
    """Check if BIMI TXT record exists."""
    bimi_domain = f"default._bimi.{domain_name}"
    try:
        answers = await asyncio.to_thread(dns.resolver.resolve, bimi_domain, "TXT")
        first_txt: str | None = None
        for rdata in answers:
            txt = _join_txt_rdata(rdata)
            if first_txt is None:
                first_txt = txt
            if txt.startswith("v=BIMI1"):
                return True, txt
        return False, first_txt
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False, None
    except Exception as exc:
        logger.debug("BIMI check for %s failed: %s", bimi_domain, exc)
        return False, None


async def _check_mta_sts(domain_name: str) -> tuple[bool, str | None]:
    """Check if _mta-sts TXT record exists."""
    mta_sts_domain = f"_mta-sts.{domain_name}"
    try:
        answers = await asyncio.to_thread(dns.resolver.resolve, mta_sts_domain, "TXT")
        first_txt: str | None = None
        for rdata in answers:
            txt = _join_txt_rdata(rdata)
            if first_txt is None:
                first_txt = txt
            if txt.startswith("v=STSv1"):
                return True, txt
        return False, first_txt
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False, None
    except Exception as exc:
        logger.debug("MTA-STS check for %s failed: %s", mta_sts_domain, exc)
        return False, None


async def _check_tls_rpt(domain_name: str) -> tuple[bool, str | None]:
    """Check if _smtp._tls TXT record exists (TLS-RPT, RFC 8460)."""
    tls_rpt_domain = f"_smtp._tls.{domain_name}"
    try:
        answers = await asyncio.to_thread(dns.resolver.resolve, tls_rpt_domain, "TXT")
        first_txt: str | None = None
        for rdata in answers:
            txt = _join_txt_rdata(rdata)
            if first_txt is None:
                first_txt = txt
            if txt.startswith("v=TLSRPTv1"):
                return True, txt
        return False, first_txt
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False, None
    except Exception as exc:
        logger.debug("TLS-RPT check for %s failed: %s", tls_rpt_domain, exc)
        return False, None


# ── Config management ────────────────────────────────────────────


async def _rebuild_opendkim_tables(domains: list[Domain]) -> None:
    """Rewrite OpenDKIM KeyTable, SigningTable, and TrustedHosts."""

    def _write() -> None:
        key_table_lines: list[str] = []
        signing_table_lines: list[str] = []
        trusted_hosts: list[str] = ["127.0.0.1", "localhost"]

        for domain in domains:
            if not domain.is_active or not domain.dkim_private_key_path:
                continue
            entry_name = f"{domain.dkim_selector}._domainkey.{domain.name}"
            key_table_lines.append(
                f"{entry_name} {domain.name}:{domain.dkim_selector}:{domain.dkim_private_key_path}"
            )
            signing_table_lines.append(f"*@{domain.name} {entry_name}")
            trusted_hosts.append(domain.name)

        Path("/etc/opendkim/KeyTable").write_text("\n".join(key_table_lines) + "\n")
        Path("/etc/opendkim/SigningTable").write_text("\n".join(signing_table_lines) + "\n")
        Path("/etc/opendkim/TrustedHosts").write_text("\n".join(trusted_hosts) + "\n")

    await asyncio.to_thread(_write)


async def _rebuild_postfix_virtual_domains(domains: list[Domain]) -> None:
    """Update Postfix virtual domain configuration.

    When domains are managed, switch from catch-all regexp to explicit hash.
    When zero domains, restore catch-all mode.

    In production mode, additionally configures ``virtual_mailbox_maps``
    and enables ``smtpd_reject_unlisted_recipient`` for strict delivery.
    """
    active_domains = [d for d in domains if d.is_active]

    def _write() -> None:
        main_cf = Path("/etc/postfix/main.cf")
        if not main_cf.exists():
            return

        content = main_cf.read_text()

        if active_domains:
            # Write virtual domains hash file
            vdomains_path = Path("/etc/postfix/virtual_domains")
            lines = [f"{d.name} OK" for d in active_domains]
            vdomains_path.write_text("\n".join(lines) + "\n")

            # Run postmap to generate .db file
            subprocess.run(
                ["postmap", str(vdomains_path)],
                check=False,
                capture_output=True,
            )

            # Update main.cf if using regexp, switch to hash
            if "regexp:/etc/postfix/virtual_domains" in content:
                content = content.replace(
                    "regexp:/etc/postfix/virtual_domains",
                    "hash:/etc/postfix/virtual_domains",
                )
                main_cf.write_text(content)

            # Production-only: enable strict recipient checking and mailbox maps
            if settings.is_production:
                subprocess.run(
                    ["postconf", "-e", "smtpd_reject_unlisted_recipient=yes"],
                    check=False,
                    capture_output=True,
                )
                subprocess.run(
                    ["postconf", "-e", "virtual_mailbox_maps=hash:/etc/postfix/virtual_mailboxes"],
                    check=False,
                    capture_output=True,
                )
        else:
            # Restore catch-all regexp mode
            if "hash:/etc/postfix/virtual_domains" in content:
                content = content.replace(
                    "hash:/etc/postfix/virtual_domains",
                    "regexp:/etc/postfix/virtual_domains",
                )
                main_cf.write_text(content)

    await asyncio.to_thread(_write)


async def rebuild_postfix_virtual_mailboxes(db: AsyncSession) -> None:
    """Query all mailboxes and regenerate ``/etc/postfix/virtual_mailboxes``.

    Each line maps an address to its Maildir path so Postfix knows which
    recipients are valid.  After writing, ``postmap`` is invoked to build
    the hash DB.
    """
    from app.mailboxes.models import Mailbox

    stmt = select(Mailbox).where(Mailbox.is_active.is_(True))
    result = await db.execute(stmt)
    mailboxes = list(result.scalars().all())

    def _write() -> None:
        vmap_path = Path("/etc/postfix/virtual_mailboxes")
        lines: list[str] = []
        for mb in mailboxes:
            local_part, domain = mb.address.split("@", maxsplit=1)
            lines.append(f"{mb.address}    {domain}/{local_part}/")
        vmap_path.write_text("\n".join(lines) + "\n")
        subprocess.run(
            ["postmap", str(vmap_path)],
            check=False,
            capture_output=True,
        )

    await asyncio.to_thread(_write)
    logger.info("Rebuilt /etc/postfix/virtual_mailboxes with %d entries.", len(mailboxes))


async def _reload_mail_services() -> None:
    """Reload Postfix and signal OpenDKIM to re-read config."""

    def _reload() -> None:
        subprocess.run(["postfix", "reload"], check=False, capture_output=True)
        subprocess.run(["pkill", "-HUP", "opendkim"], check=False, capture_output=True)

    await asyncio.to_thread(_reload)


# ── High-level API ───────────────────────────────────────────────


def _read_tunnel_hosts_from_json(path: str | Path) -> list[str]:
    """Read enabled relay hosts from the sidecar's ``tunnels.json``.

    The sidecar (``mailcue-relay-sidecar``) treats this file as its single
    source of truth — it loads it on boot and reloads on inotify.  Any
    relay listed here is one that outbound mail might actually egress
    through, so the apex SPF must authorise it.

    Returns an empty list when the file is missing, unreadable, or its
    schema doesn't match.  Never raises — SPF generation must not depend
    on the sidecar's filesystem being available.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Could not parse tunnels.json at %s — invalid JSON.", path)
        return []
    entries = data.get("tunnels") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    seen: set[str] = set()
    hosts: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # ``enabled`` defaults to True so a hand-written file that omits
        # the field is treated as live (matching the sidecar's behaviour).
        if entry.get("enabled", True) is False:
            continue
        host_value = entry.get("host")
        if not isinstance(host_value, str):
            continue
        host = host_value.strip().rstrip(".").lower()
        if host and host not in seen:
            seen.add(host)
            hosts.append(host)
    return hosts


async def _list_active_tunnel_hosts(db: AsyncSession) -> list[str]:
    """Return the deduped, ordered list of relay hostnames outbound mail
    may egress through.

    These are the relay hostnames an outbound MAIL FROM uses, so they are
    exactly the ``a:`` mechanisms the apex SPF record must authorise.
    Source-of-truth precedence:

      1. The ``tunnels`` DB table — populated when an admin configures
         tunnels via the API.
      2. ``/etc/mailcue-sidecar/tunnels.json`` — populated by hand or by
         older deployments that bootstrap the sidecar config out-of-band.
         Read directly so externally-managed sidecars still get accurate
         SPF guidance without forcing operators to mirror their config
         into the DB.
      3. Empty list — single-host deployment with no relays.
    """
    stmt = select(Tunnel).where(Tunnel.enabled.is_(True)).order_by(Tunnel.name)
    result = await db.execute(stmt)
    seen: set[str] = set()
    hosts: list[str] = []
    for t in result.scalars().all():
        host = (t.endpoint_host or "").strip().rstrip(".").lower()
        if host and host not in seen:
            seen.add(host)
            hosts.append(host)
    if hosts:
        return hosts
    return await asyncio.to_thread(_read_tunnel_hosts_from_json, settings.tunnels_config_path)


def _build_spf_expected(hostname: str, tunnel_hosts: list[str]) -> str:
    """Render the apex SPF expected value.

    With sidecar tunnels deployed, the relays do the actual delivery — the
    apex SPF must list each relay's hostname (``a:`` covers both A and AAAA)
    and use a hard fail (``-all``) since relay set is fully enumerated.
    Without tunnels we fall back to soft-fail to avoid breaking deliveries
    if the operator has additional senders we don't know about.
    """
    if tunnel_hosts:
        a_records = " ".join(f"a:{h}" for h in tunnel_hosts)
        return f"v=spf1 mx {a_records} -all"
    return f"v=spf1 mx a:{hostname} ~all"


def _build_mta_sts_expected(domain: Domain) -> str:
    """Render a stable MTA-STS expected value.

    The ``id`` tag in ``v=STSv1; id=...`` is operator-chosen and only needs
    to change when the policy file changes.  Deriving it from
    ``domain.created_at`` (or a constant fallback) keeps the displayed
    "expected" string stable across requests; drift detection further
    accepts any well-formed ``id=`` value as matching.
    """
    ts = int(domain.created_at.timestamp()) if domain.created_at is not None else 1
    return f"v=STSv1; id={ts}"


def _build_dns_records(
    domain: Domain,
    hostname: str,
    *,
    helo_spf_verified: bool = False,
    bimi_verified: bool = False,
    tunnel_hosts: list[str] | None = None,
) -> list[DnsRecordInfo]:
    """Build the list of required DNS records for a domain."""
    tunnel_hosts = tunnel_hosts or []
    records: list[DnsRecordInfo] = [
        DnsRecordInfo(
            record_type="MX",
            hostname=domain.name,
            expected_value=f"10 {hostname}.",
            verified=domain.mx_verified,
            purpose="Route incoming email to this server",
        ),
        DnsRecordInfo(
            record_type="TXT",
            hostname=domain.name,
            expected_value=_build_spf_expected(hostname, tunnel_hosts),
            verified=domain.spf_verified,
            purpose="Authorize this server to send email for the domain (SPF)",
        ),
        # HELO/EHLO SPF — receiving servers also check SPF for the HELO hostname
        DnsRecordInfo(
            record_type="TXT",
            hostname=hostname,
            expected_value="v=spf1 a -all",
            verified=helo_spf_verified,
            purpose="SPF for the mail server hostname (checked during SMTP EHLO handshake)",
        ),
        DnsRecordInfo(
            record_type="TXT",
            hostname=f"{domain.dkim_selector}._domainkey.{domain.name}",
            expected_value=domain.dkim_public_key_txt or "(DKIM key not yet generated)",
            verified=domain.dkim_verified,
            purpose="DKIM public key for email signature verification",
        ),
        DnsRecordInfo(
            record_type="TXT",
            hostname=f"_dmarc.{domain.name}",
            expected_value="v=DMARC1; p=reject; rua=mailto:postmaster@" + domain.name,
            verified=domain.dmarc_verified,
            purpose="DMARC policy for handling authentication failures (p=reject for BIMI eligibility)",
        ),
        # BIMI brand logo record
        DnsRecordInfo(
            record_type="TXT",
            hostname=f"default._bimi.{domain.name}",
            expected_value=f"v=BIMI1; l=https://{hostname}/brand/logo.svg",
            verified=bimi_verified,
            purpose="BIMI — publish a brand logo displayed by supporting mailbox providers (requires DMARC p=reject)",
        ),
        # MTA-STS policy record (RFC 8461)
        DnsRecordInfo(
            record_type="TXT",
            hostname=f"_mta-sts.{domain.name}",
            expected_value=_build_mta_sts_expected(domain),
            verified=domain.mta_sts_verified,
            purpose="MTA-STS policy enabling strict TLS for inbound email (RFC 8461)",
        ),
        # TLS-RPT reporting record (RFC 8460)
        DnsRecordInfo(
            record_type="TXT",
            hostname=f"_smtp._tls.{domain.name}",
            expected_value=f"v=TLSRPTv1; rua=mailto:tls-reports@{domain.name}",
            verified=domain.tls_rpt_verified,
            purpose="TLS reporting — receive reports about TLS connection failures (RFC 8460)",
        ),
        # PTR (reverse DNS) guidance — informational only
        DnsRecordInfo(
            record_type="PTR",
            hostname="(Configure at your VPS/hosting provider)",
            expected_value=hostname,
            verified=False,
            purpose="Reverse DNS — critical for deliverability. Set your server IP's PTR record to match the hostname",
        ),
        # A record guidance
        DnsRecordInfo(
            record_type="A",
            hostname=hostname,
            expected_value="(Your server's public IPv4 address)",
            verified=False,
            purpose="Points your mail hostname to your server's IP address",
        ),
    ]
    return records


async def add_domain(name: str, selector: str, db: AsyncSession) -> Domain:
    """Add a new domain, generate DKIM keys, and update mail service config."""
    # Generate DKIM keys
    try:
        private_key_path, public_key_txt = await _generate_dkim_keys(name, selector)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logger.warning("DKIM key generation failed for %s: %s", name, exc)
        private_key_path = None
        public_key_txt = None

    domain = Domain(
        name=name,
        dkim_selector=selector,
        dkim_private_key_path=private_key_path,
        dkim_public_key_txt=public_key_txt,
    )
    db.add(domain)
    await db.commit()
    await db.refresh(domain)

    # Rebuild config files
    async with _config_lock:
        all_domains = await _list_domains_internal(db)
        await _rebuild_opendkim_tables(all_domains)
        await _rebuild_postfix_virtual_domains(all_domains)
        if settings.is_production:
            await rebuild_postfix_virtual_mailboxes(db)
        await _reload_mail_services()

    logger.info("Domain '%s' added with DKIM selector '%s'.", name, selector)
    return domain


async def remove_domain(name: str, db: AsyncSession) -> None:
    """Remove a domain and clean up config."""
    stmt = select(Domain).where(Domain.name == name)
    result = await db.execute(stmt)
    domain = result.scalar_one_or_none()

    if domain is None:
        raise ValueError(f"Domain '{name}' not found")

    await db.delete(domain)
    await db.commit()

    # Rebuild config files
    async with _config_lock:
        all_domains = await _list_domains_internal(db)
        await _rebuild_opendkim_tables(all_domains)
        await _rebuild_postfix_virtual_domains(all_domains)
        if settings.is_production:
            await rebuild_postfix_virtual_mailboxes(db)
        await _reload_mail_services()

    logger.info("Domain '%s' removed.", name)


# ── DNS state assembly ───────────────────────────────────────────


# Slots for per-record audit timestamps on Domain.  Index aligns with the
# tuple returned from ``_run_dns_checks``.
_CANONICAL_RECORD_SLOTS: tuple[str, ...] = (
    "mx",
    "spf",
    "dkim",
    "dmarc",
    "mta_sts",
    "tls_rpt",
)


async def _run_dns_checks(domain: Domain, hostname: str) -> dict[str, tuple[bool, str | None]]:
    """Resolve every DNS record type for the domain in parallel.

    Returns a mapping keyed by logical record name (matches
    ``_CANONICAL_RECORD_SLOTS`` plus ``helo_spf`` and ``bimi``).
    """
    (
        mx_result,
        spf_result,
        helo_spf_result,
        dkim_result,
        dmarc_result,
        bimi_result,
        mta_sts_result,
        tls_rpt_result,
    ) = await asyncio.gather(
        _check_mx(domain.name, hostname),
        _check_spf(domain.name),
        _check_helo_spf(hostname),
        _check_dkim(domain.name, domain.dkim_selector, domain.dkim_public_key_txt),
        _check_dmarc(domain.name),
        _check_bimi(domain.name),
        _check_mta_sts(domain.name),
        _check_tls_rpt(domain.name),
    )
    return {
        "mx": mx_result,
        "spf": spf_result,
        "helo_spf": helo_spf_result,
        "dkim": dkim_result,
        "dmarc": dmarc_result,
        "bimi": bimi_result,
        "mta_sts": mta_sts_result,
        "tls_rpt": tls_rpt_result,
    }


def _stamp_audit_timestamps(
    domain: Domain,
    checks: dict[str, tuple[bool, str | None]],
    now: datetime,
) -> None:
    """Advance ``*_last_checked_at`` on every canonical record and
    ``*_last_verified_at`` only on records that verified."""
    for slot in _CANONICAL_RECORD_SLOTS:
        verified, _ = checks[slot]
        setattr(domain, f"{slot}_last_checked_at", now)
        if verified:
            setattr(domain, f"{slot}_last_verified_at", now)


def _record_matches(slot: str, expected: str, current: str) -> bool:
    """Return True if ``current`` is semantically equivalent to ``expected``.

    For most records this is byte-equality.  Three slots get looser checks:

    - ``dkim``: whitespace inside ``p=`` is meaningless (base64 is
      whitespace-free), so legacy DB rows with a stray space at the
      multi-string chunk boundary still match a clean DNS value.
    - ``mta_sts``: the ``id=`` tag is operator-chosen and only needs to
      change when the policy file does.  Any well-formed ``v=STSv1; id=…``
      is treated as matching.
    - ``spf``: collapse runs of whitespace before comparing so DNS providers
      that re-pretty-print the value don't trip false drift.
    """
    if slot == "dkim":
        return _normalize_dkim_txt(expected) == _normalize_dkim_txt(current)
    if slot == "mta_sts":
        prefix = "v=STSv1; id="
        stripped = current.strip()
        return stripped.startswith(prefix) and len(stripped) > len(prefix)
    if slot == "spf":
        return " ".join(expected.split()) == " ".join(current.split())
    return expected == current


def _attach_check_metadata(
    domain: Domain,
    records: list[DnsRecordInfo],
    checks: dict[str, tuple[bool, str | None]],
) -> None:
    """Populate ``current_value``, ``drift`` and per-record audit timestamps
    on a freshly built ``DnsRecordInfo`` list.

    Order MUST match ``_build_dns_records``: MX, SPF, HELO SPF, DKIM, DMARC,
    BIMI, MTA-STS, TLS-RPT, PTR, A.
    """
    # (logical_slot, audit_attr_prefix_or_None) — None means info-only,
    # no audit timestamps and no drift even if current_value is set.
    layout: tuple[tuple[str | None, str | None], ...] = (
        ("mx", "mx"),
        ("spf", "spf"),
        ("helo_spf", None),  # informational — not gated on
        ("dkim", "dkim"),
        ("dmarc", "dmarc"),
        ("bimi", None),  # informational — not gated on
        ("mta_sts", "mta_sts"),
        ("tls_rpt", "tls_rpt"),
        (None, None),  # PTR — manual / out-of-band
        (None, None),  # A   — manual / out-of-band
    )
    for record, (slot, audit) in zip(records, layout, strict=True):
        current: str | None = checks[slot][1] if slot is not None else None
        record.current_value = current
        record.drift = (
            audit is not None
            and current is not None
            and not _record_matches(audit, record.expected_value, current)
        )
        if audit is not None:
            record.last_checked_at = getattr(domain, f"{audit}_last_checked_at")
            record.last_verified_at = getattr(domain, f"{audit}_last_verified_at")


async def verify_dns(name: str, db: AsyncSession) -> DnsCheckResponse:
    """Run live DNS checks for a domain and update cached status.

    This is the only entry-point that flips the canonical ``*_verified``
    booleans on ``Domain``.  It also stamps the per-record audit
    timestamps and reports ``current_value`` / ``drift`` per record.
    """
    from app.system.service import get_server_hostname

    stmt = select(Domain).where(Domain.name == name)
    result = await db.execute(stmt)
    domain = result.scalar_one_or_none()

    if domain is None:
        raise ValueError(f"Domain '{name}' not found")

    hostname = await get_server_hostname(db)
    tunnel_hosts = await _list_active_tunnel_hosts(db)
    checks = await _run_dns_checks(domain, hostname)
    now = datetime.now(UTC)

    domain.mx_verified = checks["mx"][0]
    domain.spf_verified = checks["spf"][0]
    domain.dkim_verified = checks["dkim"][0]
    domain.dmarc_verified = checks["dmarc"][0]
    domain.mta_sts_verified = checks["mta_sts"][0]
    domain.tls_rpt_verified = checks["tls_rpt"][0]
    domain.last_dns_check = now
    _stamp_audit_timestamps(domain, checks, now)
    await db.commit()

    records = _build_dns_records(
        domain,
        hostname,
        helo_spf_verified=checks["helo_spf"][0],
        bimi_verified=checks["bimi"][0],
        tunnel_hosts=tunnel_hosts,
    )
    _attach_check_metadata(domain, records, checks)

    all_verified = all(
        [
            domain.mx_verified,
            domain.spf_verified,
            domain.dkim_verified,
            domain.dmarc_verified,
            domain.mta_sts_verified,
            domain.tls_rpt_verified,
        ]
    )

    return DnsCheckResponse(
        mx_verified=domain.mx_verified,
        spf_verified=domain.spf_verified,
        dkim_verified=domain.dkim_verified,
        dmarc_verified=domain.dmarc_verified,
        mta_sts_verified=domain.mta_sts_verified,
        tls_rpt_verified=domain.tls_rpt_verified,
        all_verified=all_verified,
        dns_records=records,
    )


async def compute_dns_state(name: str, db: AsyncSession) -> DomainDnsStateResponse:
    """Read-only DNS drift snapshot for a domain.

    Behaves like ``verify_dns`` in that it issues fresh DNS lookups and
    persists the per-record ``*_last_checked_at`` / ``*_last_verified_at``
    timestamps so the UI's "checked N min ago" indicator stays current.
    Crucially it does NOT touch the canonical ``*_verified`` booleans —
    those drive production-mode gates and must only flap when a human
    explicitly hits ``POST /verify-dns``.  Drift detection is real-time
    and needs no caching.
    """
    from app.system.service import get_server_hostname

    stmt = select(Domain).where(Domain.name == name)
    result = await db.execute(stmt)
    domain = result.scalar_one_or_none()

    if domain is None:
        raise ValueError(f"Domain '{name}' not found")

    hostname = await get_server_hostname(db)
    tunnel_hosts = await _list_active_tunnel_hosts(db)
    checks = await _run_dns_checks(domain, hostname)
    now = datetime.now(UTC)

    _stamp_audit_timestamps(domain, checks, now)
    await db.commit()

    records = _build_dns_records(
        domain,
        hostname,
        helo_spf_verified=checks["helo_spf"][0],
        bimi_verified=checks["bimi"][0],
        tunnel_hosts=tunnel_hosts,
    )
    _attach_check_metadata(domain, records, checks)

    has_drift = any(r.drift for r in records)
    # Only canonical (audited) records contribute to has_missing — info-only
    # records like HELO SPF, BIMI, PTR, A leave ``last_checked_at`` unset and
    # are excluded by design.
    has_missing = any(r.current_value is None and r.last_checked_at is not None for r in records)
    last_dns_check = max(
        (r.last_checked_at for r in records if r.last_checked_at is not None),
        default=None,
    )

    return DomainDnsStateResponse(
        domain=domain.name,
        records=records,
        has_drift=has_drift,
        has_missing=has_missing,
        last_dns_check=last_dns_check,
    )


async def get_domain_detail(name: str, db: AsyncSession) -> Domain:
    """Get a single domain by name."""
    stmt = select(Domain).where(Domain.name == name)
    result = await db.execute(stmt)
    domain = result.scalar_one_or_none()
    if domain is None:
        raise ValueError(f"Domain '{name}' not found")
    return domain


async def list_domains(db: AsyncSession) -> list[Domain]:
    """List all managed domains."""
    return await _list_domains_internal(db)


async def _list_domains_internal(db: AsyncSession) -> list[Domain]:
    """Internal helper to list all domains."""
    stmt = select(Domain).order_by(Domain.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())
