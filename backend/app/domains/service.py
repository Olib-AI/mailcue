"""Domain management business logic — DKIM generation, DNS validation, config management."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import dns.resolver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domains.models import Domain
from app.domains.schemas import DnsCheckResponse, DnsRecordInfo

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
                "rsa-sha256",
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
            # Extract the p= value from the TXT record
            # Format: selector._domainkey\tIN\tTXT\t( "v=DKIM1; h=...; k=rsa; p=..." )
            public_key_txt = raw

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


async def _check_mx(domain_name: str, hostname: str) -> tuple[bool, str | None]:
    """Check if MX record points to our hostname."""
    try:
        answers = await asyncio.to_thread(dns.resolver.resolve, domain_name, "MX")
        for rdata in answers:
            mx_host = str(rdata.exchange).rstrip(".")
            if mx_host == hostname:
                return True, mx_host
        # Return first MX found even if not matching
        first_mx = str(next(iter(answers)).exchange).rstrip(".") if answers else None
        return False, first_mx
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False, None
    except Exception as exc:
        logger.debug("MX check for %s failed: %s", domain_name, exc)
        return False, None


async def _check_spf(domain_name: str) -> tuple[bool, str | None]:
    """Check if TXT record contains a valid SPF record."""
    try:
        answers = await asyncio.to_thread(dns.resolver.resolve, domain_name, "TXT")
        for rdata in answers:
            txt = str(rdata).strip('"')
            if txt.startswith("v=spf1"):
                return True, txt
        return False, None
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
        for rdata in answers:
            txt = str(rdata).strip('"')
            if "p=" in txt and expected_public_key:
                # Extract p= value for comparison
                return True, txt
            elif "p=" in txt:
                return True, txt
        return False, None
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
        for rdata in answers:
            txt = str(rdata).strip('"')
            if txt.startswith("v=DMARC1"):
                return True, txt
        return False, None
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False, None
    except Exception as exc:
        logger.debug("DMARC check for %s failed: %s", dmarc_domain, exc)
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
        else:
            # Restore catch-all regexp mode
            if "hash:/etc/postfix/virtual_domains" in content:
                content = content.replace(
                    "hash:/etc/postfix/virtual_domains",
                    "regexp:/etc/postfix/virtual_domains",
                )
                main_cf.write_text(content)

    await asyncio.to_thread(_write)


async def _reload_mail_services() -> None:
    """Reload Postfix and signal OpenDKIM to re-read config."""

    def _reload() -> None:
        subprocess.run(["postfix", "reload"], check=False, capture_output=True)
        subprocess.run(["pkill", "-HUP", "opendkim"], check=False, capture_output=True)

    await asyncio.to_thread(_reload)


# ── High-level API ───────────────────────────────────────────────


def _build_dns_records(domain: Domain, hostname: str) -> list[DnsRecordInfo]:
    """Build the list of required DNS records for a domain."""
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
            expected_value=f"v=spf1 mx a:{hostname} ~all",
            verified=domain.spf_verified,
            purpose="Authorize this server to send email for the domain (SPF)",
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
            expected_value="v=DMARC1; p=quarantine; rua=mailto:postmaster@" + domain.name,
            verified=domain.dmarc_verified,
            purpose="DMARC policy for handling authentication failures",
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
        await _reload_mail_services()

    logger.info("Domain '%s' removed.", name)


async def verify_dns(name: str, db: AsyncSession) -> DnsCheckResponse:
    """Run live DNS checks for a domain and update cached status."""
    from app.system.service import get_server_hostname

    stmt = select(Domain).where(Domain.name == name)
    result = await db.execute(stmt)
    domain = result.scalar_one_or_none()

    if domain is None:
        raise ValueError(f"Domain '{name}' not found")

    hostname = await get_server_hostname(db)

    # Run all checks concurrently
    mx_result, spf_result, dkim_result, dmarc_result = await asyncio.gather(
        _check_mx(domain.name, hostname),
        _check_spf(domain.name),
        _check_dkim(domain.name, domain.dkim_selector, domain.dkim_public_key_txt),
        _check_dmarc(domain.name),
    )

    domain.mx_verified = mx_result[0]
    domain.spf_verified = spf_result[0]
    domain.dkim_verified = dkim_result[0]
    domain.dmarc_verified = dmarc_result[0]
    domain.last_dns_check = datetime.now(UTC)
    await db.commit()

    # Build DNS records with current values
    records = _build_dns_records(domain, hostname)
    # Attach current values from the check results
    current_values = [mx_result[1], spf_result[1], dkim_result[1], dmarc_result[1]]
    for record, current_value in zip(records, current_values, strict=False):
        record.current_value = current_value

    all_verified = all(
        [
            domain.mx_verified,
            domain.spf_verified,
            domain.dkim_verified,
            domain.dmarc_verified,
        ]
    )

    return DnsCheckResponse(
        mx_verified=domain.mx_verified,
        spf_verified=domain.spf_verified,
        dkim_verified=domain.dkim_verified,
        dmarc_verified=domain.dmarc_verified,
        all_verified=all_verified,
        dns_records=records,
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
