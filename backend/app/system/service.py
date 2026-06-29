"""System settings business logic — server hostname & TLS certificate management."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.system.models import ServerSettings, TlsCertificate

logger = logging.getLogger("mailcue.system")

CERT_DIR = Path("/etc/ssl/mailcue")
SERVER_ONLY_CERT = CERT_DIR / "server-only.crt"
FULL_CHAIN_CERT = CERT_DIR / "server.crt"
SERVER_KEY = CERT_DIR / "server.key"
CA_CERT = CERT_DIR / "ca.crt"


# ── Hostname ────────────────────────────────────────────────────


async def get_server_hostname(db: AsyncSession) -> str:
    """Read hostname from DB, fall back to settings.hostname ENV var."""
    stmt = select(ServerSettings).where(ServerSettings.id == 1)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row and row.hostname:
        return row.hostname
    return settings.hostname


async def set_server_hostname(hostname: str, db: AsyncSession) -> str:
    """Upsert hostname into server_settings row. Return saved value."""
    stmt = select(ServerSettings).where(ServerSettings.id == 1)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row:
        row.hostname = hostname
    else:
        row = ServerSettings(id=1, hostname=hostname)
        db.add(row)
    await db.commit()
    return hostname


async def get_server_settings(db: AsyncSession) -> dict[str, Any]:
    """Read server settings from DB, fall back to settings.hostname ENV var."""
    stmt = select(ServerSettings).where(ServerSettings.id == 1)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    hostname = settings.hostname
    catch_all_enabled = False
    if row:
        if row.hostname:
            hostname = row.hostname
        catch_all_enabled = row.catch_all_enabled
    return {"hostname": hostname, "catch_all_enabled": catch_all_enabled}


async def update_server_settings(
    hostname: str, catch_all_enabled: bool, db: AsyncSession
) -> dict[str, Any]:
    """Upsert settings into server_settings row. Return saved values."""
    stmt = select(ServerSettings).where(ServerSettings.id == 1)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row:
        row.hostname = hostname
        row.catch_all_enabled = catch_all_enabled
    else:
        row = ServerSettings(id=1, hostname=hostname, catch_all_enabled=catch_all_enabled)
        db.add(row)
    await db.commit()

    # 1. Update Dovecot config
    update_dovecot_catchall_config(catch_all_enabled)

    # 2. Rebuild Postfix virtual mailboxes/catchall
    from app.domains.service import rebuild_postfix_virtual_mailboxes

    await rebuild_postfix_virtual_mailboxes(db)

    # 3. Reload services (Postfix and Dovecot)
    await _reload_tls_services()

    return {"hostname": hostname, "catch_all_enabled": catch_all_enabled}


def update_dovecot_catchall_config(enabled: bool) -> None:
    """Comment/uncomment the catch-all fallback userdb block in /etc/dovecot/dovecot.conf."""
    path = Path("/etc/dovecot/dovecot.conf")
    if not path.exists():
        logger.debug("Dovecot config file not found at %s. Skipping update.", path)
        return
    try:
        content = path.read_text(encoding="utf-8")

        # We want to match the static userdb block
        import re

        pattern = re.compile(
            r"(?:#\s*)?userdb\s*\{\s*\r?\n"
            r"(?:#\s*)?driver\s*=\s*static\s*\r?\n"
            r"(?:#\s*)?args\s*=\s*uid=5000\s+gid=5000\s+home=/var/mail/vhosts/%d/%n\s+allow_all_users=yes\s*\r?\n"
            r"(?:#\s*)?\}",
            re.MULTILINE,
        )

        if enabled:
            replacement = (
                "userdb {\n"
                "  driver = static\n"
                "  args = uid=5000 gid=5000 home=/var/mail/vhosts/%d/%n allow_all_users=yes\n"
                "}"
            )
        else:
            replacement = (
                "#userdb {\n"
                "#  driver = static\n"
                "#  args = uid=5000 gid=5000 home=/var/mail/vhosts/%d/%n allow_all_users=yes\n"
                "#}"
            )

        new_content, count = pattern.subn(replacement, content)
        if count > 0:
            path.write_text(new_content, encoding="utf-8")
            logger.info(
                "Successfully updated Dovecot dovecot.conf catch-all userdb block (enabled=%s).",
                enabled,
            )
        else:
            logger.warning(
                "Could not find the catch-all fallback userdb block in /etc/dovecot/dovecot.conf to update."
            )
    except Exception as exc:
        logger.exception("Failed to update Dovecot dovecot.conf: %s", exc)


# ── TLS Certificate ─────────────────────────────────────────────


def _validate_cert_key_pair(
    cert_pem: str,
    key_pem: str,
) -> x509.Certificate:
    """Parse PEM cert & key, verify they match and cert is not expired.

    Returns the parsed Certificate on success.
    Raises ``ValueError`` on any validation failure.
    """
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
    except Exception as exc:
        raise ValueError(f"Invalid certificate PEM: {exc}") from exc

    try:
        private_key = serialization.load_pem_private_key(
            key_pem.encode(),
            password=None,
        )
    except Exception as exc:
        raise ValueError(f"Invalid private key PEM: {exc}") from exc

    # Compare DER-encoded public keys to verify cert/key match
    cert_pub_der = cert.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key_pub_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if cert_pub_der != key_pub_der:
        raise ValueError("Certificate and private key do not match (public keys differ).")

    now = datetime.now(UTC)
    if cert.not_valid_after_utc.replace(tzinfo=UTC) < now:
        raise ValueError(
            f"Certificate has expired (not_after={cert.not_valid_after_utc.isoformat()})."
        )

    return cert


def _extract_cert_metadata(cert: x509.Certificate) -> dict[str, Any]:
    """Extract CN, SAN DNS names, validity dates, SHA-256 fingerprint."""
    cn_attrs = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
    common_name = cn_attrs[0].value if cn_attrs else None

    dns_names: list[str] = []
    try:
        san_ext = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName,
        )
        dns_names = san_ext.value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        pass

    return {
        "common_name": common_name,
        "san_dns_names": dns_names,
        "not_before": cert.not_valid_before_utc.replace(tzinfo=UTC),
        "not_after": cert.not_valid_after_utc.replace(tzinfo=UTC),
        "fingerprint_sha256": cert.fingerprint(hashes.SHA256()).hex(":"),
    }


def _write_certs_to_disk_sync(
    cert_pem: str,
    key_pem: str,
    ca_pem: str | None,
) -> None:
    """Write certificate files to /etc/ssl/mailcue/ (synchronous)."""
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    # server-only.crt — just the leaf cert
    SERVER_ONLY_CERT.write_text(cert_pem)

    # server.crt — full chain (cert + CA if provided)
    full_chain = cert_pem
    if ca_pem:
        full_chain = cert_pem.rstrip("\n") + "\n" + ca_pem
    FULL_CHAIN_CERT.write_text(full_chain)

    # server.key — private key (restrictive permissions)
    SERVER_KEY.write_text(key_pem)
    os.chmod(SERVER_KEY, 0o600)

    # ca.crt — optional CA/intermediate chain
    if ca_pem:
        CA_CERT.write_text(ca_pem)
    elif CA_CERT.exists():
        CA_CERT.unlink()


async def _write_certs_to_disk(
    cert_pem: str,
    key_pem: str,
    ca_pem: str | None,
) -> None:
    """Async wrapper — write cert files in a thread."""
    await asyncio.to_thread(_write_certs_to_disk_sync, cert_pem, key_pem, ca_pem)


async def _reload_tls_services() -> None:
    """Reload Postfix and Dovecot to pick up new certificates."""
    for cmd in (["postfix", "reload"], ["doveadm", "reload"]):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(
                    "%s reload failed (rc=%d): %s",
                    cmd[0],
                    proc.returncode,
                    stderr.decode().strip(),
                )
        except FileNotFoundError:
            logger.debug("%s not found — skipping reload.", cmd[0])


async def get_tls_certificate_status(db: AsyncSession) -> dict[str, Any] | None:
    """Return TLS certificate metadata from DB. Never returns PEM content."""
    stmt = select(TlsCertificate).where(TlsCertificate.id == 1)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return {
        "configured": True,
        "common_name": row.common_name,
        "san_dns_names": row.san_dns_names or [],
        "not_before": row.not_before.isoformat() if row.not_before else None,
        "not_after": row.not_after.isoformat() if row.not_after else None,
        "fingerprint_sha256": row.fingerprint_sha256,
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
    }


async def upload_tls_certificate(
    cert_pem: str,
    key_pem: str,
    ca_pem: str | None,
    db: AsyncSession,
) -> dict[str, Any]:
    """Validate, store, deploy, and reload a custom TLS certificate."""
    cert = _validate_cert_key_pair(cert_pem, key_pem)

    if ca_pem:
        try:
            x509.load_pem_x509_certificate(ca_pem.encode())
        except Exception as exc:
            raise ValueError(f"Invalid CA certificate PEM: {exc}") from exc

    metadata = _extract_cert_metadata(cert)

    # Upsert DB row
    stmt = select(TlsCertificate).where(TlsCertificate.id == 1)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if row:
        row.certificate_pem = cert_pem
        row.private_key_pem = key_pem
        row.ca_certificate_pem = ca_pem
        row.common_name = metadata["common_name"]
        row.san_dns_names = metadata["san_dns_names"]
        row.not_before = metadata["not_before"]
        row.not_after = metadata["not_after"]
        row.fingerprint_sha256 = metadata["fingerprint_sha256"]
        row.uploaded_at = now
    else:
        row = TlsCertificate(
            id=1,
            certificate_pem=cert_pem,
            private_key_pem=key_pem,
            ca_certificate_pem=ca_pem,
            common_name=metadata["common_name"],
            san_dns_names=metadata["san_dns_names"],
            not_before=metadata["not_before"],
            not_after=metadata["not_after"],
            fingerprint_sha256=metadata["fingerprint_sha256"],
            uploaded_at=now,
        )
        db.add(row)
    await db.commit()

    # Write to disk and reload services
    await _write_certs_to_disk(cert_pem, key_pem, ca_pem)
    await _reload_tls_services()

    return {
        "configured": True,
        "common_name": metadata["common_name"],
        "san_dns_names": metadata["san_dns_names"],
        "not_before": metadata["not_before"].isoformat(),
        "not_after": metadata["not_after"].isoformat(),
        "fingerprint_sha256": metadata["fingerprint_sha256"],
        "uploaded_at": now.isoformat(),
    }


async def get_production_status(db: AsyncSession) -> dict[str, Any]:
    """Compute a production-readiness report from config and filesystem state."""
    from app.domains.models import Domain

    # Count domains
    stmt = select(Domain)
    result = await db.execute(stmt)
    all_domains = list(result.scalars().all())
    domains_configured = len(all_domains)
    domains_verified = sum(
        1
        for d in all_domains
        if all(
            [
                d.mx_verified,
                d.spf_verified,
                d.dkim_verified,
                d.dmarc_verified,
                d.mta_sts_verified,
                d.tls_rpt_verified,
            ]
        )
    )

    # TLS check: external cert paths or uploaded cert on disk
    has_external_cert = bool(
        settings.tls_cert_path
        and settings.tls_key_path
        and Path(settings.tls_cert_path).exists()
        and Path(settings.tls_key_path).exists()
    )
    has_uploaded_cert = FULL_CHAIN_CERT.exists() and SERVER_KEY.exists()
    tls_configured = has_external_cert or has_uploaded_cert

    return {
        "mode": settings.mode,
        "tls_configured": tls_configured,
        "domains_configured": domains_configured,
        "domains_verified": domains_verified,
        "postfix_strict_mode": settings.is_production,
        "dovecot_tls_required": settings.is_production and tls_configured,
        "secure_cookies": settings.is_production,
        "acme_configured": bool(settings.acme_email),
        # Test-only feature surface.  These mirror the conditional router
        # registration in ``app.main`` and the ``/inject`` route guard so
        # the UI can hide menu items it would otherwise dead-link to.
        "features": {
            "inject": not settings.is_production,
            "messaging_sandbox": settings.sandbox_enabled and not settings.is_production,
            "httpbin": not settings.is_production,
        },
    }


async def restore_custom_certs(db: AsyncSession) -> None:
    """Restore custom TLS certificates from DB to disk on startup."""
    stmt = select(TlsCertificate).where(TlsCertificate.id == 1)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return

    logger.info("Restoring custom TLS certificate (CN=%s) from database.", row.common_name)
    await _write_certs_to_disk(row.certificate_pem, row.private_key_pem, row.ca_certificate_pem)
    await _reload_tls_services()
