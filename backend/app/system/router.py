"""System endpoints — TLS certificate info, download, and server settings."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.database import get_db
from app.dependencies import require_admin
from app.system.service import (
    get_production_status,
    get_server_hostname,
    get_tls_certificate_status,
    set_server_hostname,
    upload_tls_certificate,
)

router = APIRouter(prefix="/system", tags=["System"])

CA_CERT_PATH = Path("/etc/ssl/mailcue/ca.crt")
SERVER_CERT_PATH = Path("/etc/ssl/mailcue/server-only.crt")
# Let's Encrypt / ACME certificate (production mode)
ACME_CERT_PATH = Path("/etc/ssl/mailcue/fullchain.pem")
# Fallback for legacy single-cert setups (pre-CA split)
LEGACY_CERT_PATH = Path("/etc/ssl/mailcue/server.crt")


def _parse_cert(pem_path: Path) -> x509.Certificate:
    """Read and parse a PEM certificate from disk."""
    if not pem_path.exists():
        raise HTTPException(
            status_code=404,
            detail="TLS certificate not found on this server.",
        )
    try:
        return x509.load_pem_x509_certificate(pem_path.read_bytes())
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to parse TLS certificate.",
        ) from exc


def _extract_dn_attr(
    name: x509.Name,
    oid: x509.oid.ObjectIdentifier,
) -> str | None:
    """Extract a single attribute from a distinguished name."""
    attrs = name.get_attributes_for_oid(oid)
    return attrs[0].value if attrs else None


def _cert_metadata(cert: x509.Certificate) -> dict:
    """Build a metadata dict from a parsed certificate."""
    oid = x509.oid.NameOID

    # Subject Alternative Names (DNS + IP + email)
    dns_sans: list[str] = []
    ip_sans: list[str] = []
    email_sans: list[str] = []
    try:
        san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_sans = san_ext.value.get_values_for_type(x509.DNSName)
        ip_sans = [str(ip) for ip in san_ext.value.get_values_for_type(x509.IPAddress)]
        email_sans = san_ext.value.get_values_for_type(x509.RFC822Name)
    except x509.ExtensionNotFound:
        pass

    # Key usage
    key_usage: list[str] = []
    try:
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        for attr in (
            "digital_signature",
            "key_encipherment",
            "key_agreement",
            "key_cert_sign",
            "crl_sign",
            "content_commitment",
            "data_encipherment",
        ):
            if getattr(ku, attr, False):
                key_usage.append(attr)
        # encipher_only / decipher_only are only defined when key_agreement
        # is true; accessing them otherwise raises ValueError.
        if ku.key_agreement:
            for attr in ("encipher_only", "decipher_only"):
                if getattr(ku, attr, False):
                    key_usage.append(attr)
    except x509.ExtensionNotFound:
        pass

    # Extended key usage
    ext_key_usage: list[str] = []
    try:
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        eku_names = {
            x509.oid.ExtendedKeyUsageOID.SERVER_AUTH: "serverAuth",
            x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH: "clientAuth",
            x509.oid.ExtendedKeyUsageOID.EMAIL_PROTECTION: "emailProtection",
            x509.oid.ExtendedKeyUsageOID.CODE_SIGNING: "codeSigning",
            x509.oid.ExtendedKeyUsageOID.TIME_STAMPING: "timeStamping",
        }
        for usage in eku:
            ext_key_usage.append(eku_names.get(usage, usage.dotted_string))
    except x509.ExtensionNotFound:
        pass

    # Basic constraints
    is_ca = False
    try:
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints).value
        is_ca = bc.ca
    except x509.ExtensionNotFound:
        pass

    return {
        "fingerprint_sha256": cert.fingerprint(hashes.SHA256()).hex(":"),
        "fingerprint_sha1": cert.fingerprint(hashes.SHA1()).hex(":"),
        "serial_number": format(cert.serial_number, "x"),
        "version": f"v{cert.version.value + 1}",
        "signature_algorithm": cert.signature_algorithm_oid._name,
        "subject": {
            "common_name": _extract_dn_attr(cert.subject, oid.COMMON_NAME),
            "organization": _extract_dn_attr(cert.subject, oid.ORGANIZATION_NAME),
            "organizational_unit": _extract_dn_attr(cert.subject, oid.ORGANIZATIONAL_UNIT_NAME),
            "country": _extract_dn_attr(cert.subject, oid.COUNTRY_NAME),
            "state": _extract_dn_attr(cert.subject, oid.STATE_OR_PROVINCE_NAME),
            "locality": _extract_dn_attr(cert.subject, oid.LOCALITY_NAME),
            "email": _extract_dn_attr(cert.subject, oid.EMAIL_ADDRESS),
            "dn": cert.subject.rfc4514_string(),
        },
        "issuer": {
            "common_name": _extract_dn_attr(cert.issuer, oid.COMMON_NAME),
            "organization": _extract_dn_attr(cert.issuer, oid.ORGANIZATION_NAME),
            "organizational_unit": _extract_dn_attr(cert.issuer, oid.ORGANIZATIONAL_UNIT_NAME),
            "country": _extract_dn_attr(cert.issuer, oid.COUNTRY_NAME),
            "state": _extract_dn_attr(cert.issuer, oid.STATE_OR_PROVINCE_NAME),
            "locality": _extract_dn_attr(cert.issuer, oid.LOCALITY_NAME),
            "email": _extract_dn_attr(cert.issuer, oid.EMAIL_ADDRESS),
            "dn": cert.issuer.rfc4514_string(),
        },
        "validity": {
            "not_before": cert.not_valid_before_utc.replace(tzinfo=UTC).isoformat(),
            "not_after": cert.not_valid_after_utc.replace(tzinfo=UTC).isoformat(),
        },
        "san": {
            "dns_names": dns_sans,
            "ip_addresses": ip_sans,
            "emails": email_sans,
        },
        "is_ca": is_ca,
        "key_usage": key_usage,
        "extended_key_usage": ext_key_usage,
        "public_key_algorithm": cert.public_key().__class__.__name__,
        "public_key_size": cert.public_key().key_size,
    }


@router.get("/certificate")
async def get_certificate_info(
    _admin: User = Depends(require_admin),
) -> dict:
    """Return metadata for both the server and CA certificates. **Admin only.**"""
    # Prefer ACME/Let's Encrypt cert in production
    if ACME_CERT_PATH.exists():
        cert = _parse_cert(ACME_CERT_PATH)
        return {
            "server": _cert_metadata(cert),
            "ca": None,  # Let's Encrypt chain is in fullchain.pem
            "source": "letsencrypt",
        }

    # Split CA/server certs (test mode self-signed)
    if CA_CERT_PATH.exists() and SERVER_CERT_PATH.exists():
        ca_cert = _parse_cert(CA_CERT_PATH)
        server_cert = _parse_cert(SERVER_CERT_PATH)
        return {
            "server": _cert_metadata(server_cert),
            "ca": _cert_metadata(ca_cert),
            "source": "self-signed",
        }

    cert = _parse_cert(LEGACY_CERT_PATH)
    return {
        "server": _cert_metadata(cert),
        "ca": None,
        "source": "self-signed",
    }


@router.get("/certificate/download")
async def download_certificate(
    _admin: User = Depends(require_admin),
) -> Response:
    """Download the CA certificate as a PEM file. **Admin only.**"""
    # Prefer the dedicated CA cert; fall back to legacy single cert
    path = CA_CERT_PATH if CA_CERT_PATH.exists() else LEGACY_CERT_PATH
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="TLS certificate not found on this server.",
        )
    return Response(
        content=path.read_bytes(),
        media_type="application/x-pem-file",
        headers={"Content-Disposition": 'attachment; filename="mailcue-ca.crt"'},
    )


# ── Server settings ─────────────────────────────────────────────


class ServerSettingsResponse(BaseModel):
    hostname: str


class UpdateServerSettingsRequest(BaseModel):
    hostname: str


@router.get("/settings", response_model=ServerSettingsResponse)
async def get_settings(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ServerSettingsResponse:
    """Return server-wide settings. **Admin only.**"""
    hostname = await get_server_hostname(db)
    return ServerSettingsResponse(hostname=hostname)


@router.put("/settings", response_model=ServerSettingsResponse)
async def update_settings(
    body: UpdateServerSettingsRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ServerSettingsResponse:
    """Update server-wide settings. **Admin only.**"""
    hostname = await set_server_hostname(body.hostname, db)
    return ServerSettingsResponse(hostname=hostname)


# ── TLS Certificate ─────────────────────────────────────────────


class TlsCertificateStatusResponse(BaseModel):
    configured: bool
    common_name: str | None = None
    san_dns_names: list[str] = []
    not_before: str | None = None
    not_after: str | None = None
    fingerprint_sha256: str | None = None
    uploaded_at: str | None = None


class UploadTlsCertificateRequest(BaseModel):
    certificate: str
    private_key: str
    ca_certificate: str | None = None


@router.get("/tls", response_model=TlsCertificateStatusResponse)
async def get_tls_status(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TlsCertificateStatusResponse:
    """Return custom TLS certificate metadata. **Admin only.** No PEM content."""
    status = await get_tls_certificate_status(db)
    if status is None:
        return TlsCertificateStatusResponse(configured=False)
    return TlsCertificateStatusResponse(**status)


@router.put("/tls", response_model=TlsCertificateStatusResponse)
async def upload_tls(
    body: UploadTlsCertificateRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TlsCertificateStatusResponse:
    """Upload a custom TLS certificate + private key. **Admin only.**"""
    try:
        result = await upload_tls_certificate(
            cert_pem=body.certificate,
            key_pem=body.private_key,
            ca_pem=body.ca_certificate,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TlsCertificateStatusResponse(**result)


# ── Production status ────────────────────────────────────────────


class ProductionStatusResponse(BaseModel):
    mode: str
    tls_configured: bool
    domains_configured: int
    domains_verified: int
    postfix_strict_mode: bool
    dovecot_tls_required: bool
    secure_cookies: bool
    acme_configured: bool


@router.get("/production-status", response_model=ProductionStatusResponse)
async def production_status(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProductionStatusResponse:
    """Return the current production readiness status. **Admin only.**"""
    data = await get_production_status(db)
    return ProductionStatusResponse(**data)
