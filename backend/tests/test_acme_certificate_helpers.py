"""Regression tests for the shell helpers used by ACME certificate setup."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _write_certificate(path: Path, hostnames: list[str]) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostnames[0])])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname) for hostname in hostnames]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def _certificate_covers(helper: Path, certificate: Path, hostname: str) -> bool:
    result = subprocess.run(
        [
            "/bin/sh",
            "-c",
            '. "$1"; certificate_covers_host "$2" "$3"',
            "mailcue-acme-test",
            str(helper),
            str(certificate),
            hostname,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def test_certificate_hostname_match_does_not_trust_openssl_mismatch_exit_code(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    helper = repository_root / "rootfs/usr/local/lib/mailcue-acme.sh"
    mail_only = tmp_path / "mail-only.pem"
    expanded = tmp_path / "expanded.pem"
    _write_certificate(mail_only, ["mail.example.com"])
    _write_certificate(expanded, ["mail.example.com", "mta-sts.example.com"])

    assert _certificate_covers(helper, mail_only, "mail.example.com") is True
    assert _certificate_covers(helper, mail_only, "mta-sts.example.com") is False
    assert _certificate_covers(helper, expanded, "mail.example.com") is True
    assert _certificate_covers(helper, expanded, "mta-sts.example.com") is True
