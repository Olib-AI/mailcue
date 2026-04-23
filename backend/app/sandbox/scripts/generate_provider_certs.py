"""Generate CA-signed leaf TLS certificates for every real phone-provider
hostname the Mailcue sandbox impersonates.

Purpose
-------
In a development environment, the fase backend resolves the real public
hostnames (``api.twilio.com`` etc.) to the Mailcue container via Docker's
``extra_hosts``.  Mailcue's Nginx terminates TLS using the leaf cert
produced by this script; because the cert is signed by the existing
Mailcue Root CA (already trusted by fase via ``update-ca-certificates``)
the provider SDKs complete their TLS handshake successfully without any
code branching.

The script is idempotent: already-present leaf certs are left untouched
unless ``--force`` is supplied.  It is safe to invoke on every container
startup — the cheapest path is a single directory ``os.listdir`` call.

Invocation
----------
::

    python -m app.sandbox.scripts.generate_provider_certs

    # Optional: regenerate everything
    python -m app.sandbox.scripts.generate_provider_certs --force

Dependencies
------------
Only ``cryptography`` (already installed via ``python-jose[cryptography]``).
No shell-outs to ``openssl``.

Outputs
-------
* ``${leaves_dir}/{hostname}/fullchain.pem`` — leaf + CA (for Nginx)
* ``${leaves_dir}/{hostname}/privkey.pem``   — 2048-bit RSA private key
* ``${ca_dir}/ca.crt`` / ``ca.key``          — CA (created if missing, else reused)

Environment
-----------
* ``MAILCUE_PROVIDER_CA_DIR``     — defaults to ``/etc/ssl/mailcue``
* ``MAILCUE_PROVIDER_LEAVES_DIR`` — defaults to ``/var/lib/mailcue/certs/provider_leaves``
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger("mailcue.sandbox.certs")


# Canonical list of phone-provider hostnames whose TLS we impersonate.
# New hostnames only need to be appended here — Nginx config generation
# (``generate_provider_nginx.py``) consumes the same list.
PROVIDER_HOSTNAMES: tuple[str, ...] = (
    "api.twilio.com",
    "trusthub.twilio.com",
    "messaging.twilio.com",
    "numbers.twilio.com",
    "messaging.bandwidth.com",
    "voice.bandwidth.com",
    "dashboard.bandwidth.com",
    "numbers.bandwidth.com",
    "api.nexmo.com",
    "rest.nexmo.com",
    "api.vonage.com",
    "api.plivo.com",
    "api.telnyx.com",
)


CA_VALIDITY_DAYS: int = 365 * 10  # 10 years, matches init-mailcue.sh
LEAF_VALIDITY_DAYS: int = 365 * 5  # 5 years — private dev CA, long-lived on purpose


def _default_ca_dir() -> Path:
    return Path(os.environ.get("MAILCUE_PROVIDER_CA_DIR", "/etc/ssl/mailcue"))


def _default_leaves_dir() -> Path:
    return Path(
        os.environ.get(
            "MAILCUE_PROVIDER_LEAVES_DIR",
            "/var/lib/mailcue/certs/provider_leaves",
        )
    )


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.UTC)


def _load_or_create_ca(ca_dir: Path) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    """Return (ca_key, ca_cert) — create if absent.

    The CA is identical in subject to the one produced by
    ``init-mailcue.sh`` so an already-booted container's CA is reused
    verbatim.  The ``init-mailcue.sh`` script runs FIRST in the s6
    oneshot chain so in practice we always find an existing CA.
    """
    ca_dir.mkdir(parents=True, exist_ok=True)
    ca_key_path = ca_dir / "ca.key"
    ca_crt_path = ca_dir / "ca.crt"

    if ca_key_path.exists() and ca_crt_path.exists():
        key_bytes = ca_key_path.read_bytes()
        crt_bytes = ca_crt_path.read_bytes()
        ca_key_obj = serialization.load_pem_private_key(key_bytes, password=None)
        if not isinstance(ca_key_obj, rsa.RSAPrivateKey):
            raise RuntimeError(f"Unexpected CA key type in {ca_key_path}")
        ca_cert = x509.load_pem_x509_certificate(crt_bytes)
        logger.info("Loaded existing Mailcue CA from %s", ca_crt_path)
        return ca_key_obj, ca_cert

    logger.info("Generating new Mailcue Root CA at %s", ca_dir)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Georgia"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Stone Mountain"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Olib AI"),
            x509.NameAttribute(
                NameOID.ORGANIZATIONAL_UNIT_NAME,
                "MailCue Certificate Authority",
            ),
            x509.NameAttribute(NameOID.COMMON_NAME, "MailCue Root CA"),
        ]
    )
    now = _utcnow()
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=CA_VALIDITY_DAYS))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(private_key=ca_key, algorithm=hashes.SHA256())
    )
    ca_key_path.write_bytes(
        ca_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    os.chmod(ca_key_path, 0o600)
    ca_crt_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    os.chmod(ca_crt_path, 0o644)
    return ca_key, ca_cert


def _san_for_hostname(hostname: str) -> x509.SubjectAlternativeName:
    entries: list[x509.GeneralName] = [x509.DNSName(hostname)]
    # Include a few known aliases so SNI-mismatching clients still
    # handshake — e.g. some old SDKs hit ``nexmo.com`` instead of
    # ``api.nexmo.com``.  For every hostname we also include the bare
    # apex if it's a multi-label name (``messaging.bandwidth.com`` ->
    # ``bandwidth.com`` for Server Name Indication tolerance).
    if hostname.count(".") >= 2:
        apex = hostname.split(".", 1)[1]
        entries.append(x509.DNSName(apex))
    return x509.SubjectAlternativeName(entries)


def _generate_leaf(
    hostname: str,
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Olib AI"),
            x509.NameAttribute(
                NameOID.ORGANIZATIONAL_UNIT_NAME,
                "MailCue Sandbox Provider Proxy",
            ),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ]
    )
    now = _utcnow()
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=LEAF_VALIDITY_DAYS))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [
                    x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                    x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()),
            critical=False,
        )
        .add_extension(_san_for_hostname(hostname), critical=False)
    )
    return leaf_key, builder.sign(private_key=ca_key, algorithm=hashes.SHA256())


def _write_leaf(
    leaves_dir: Path,
    hostname: str,
    leaf_key: rsa.RSAPrivateKey,
    leaf_cert: x509.Certificate,
    ca_cert: x509.Certificate,
) -> None:
    host_dir = leaves_dir / hostname
    host_dir.mkdir(parents=True, exist_ok=True)
    key_path = host_dir / "privkey.pem"
    fullchain_path = host_dir / "fullchain.pem"

    key_path.write_bytes(
        leaf_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    os.chmod(key_path, 0o600)

    # Serve ONLY the leaf, not leaf+root.  Including a self-signed root
    # in the TLS handshake chain makes OpenSSL (and therefore every
    # Python SDK via ``ssl.create_default_context``) fail with
    # ``X509_V_ERR_SELF_SIGNED_CERT_IN_CHAIN`` (error 19) even when the
    # root is separately installed in the client's trust store.  The
    # CA is distributed to consumer projects via
    # ``update-ca-certificates`` at image build time, so it does not
    # need to ride along in the TLS handshake.
    fullchain_path.write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
    os.chmod(fullchain_path, 0o644)


def _fingerprint(cert: x509.Certificate) -> str:
    return cert.fingerprint(hashes.SHA256()).hex()


def _leaf_matches_ca(fullchain_path: Path, ca_ski: bytes | None) -> bool:
    """Return True when *fullchain_path* was signed by the CA whose
    SubjectKeyIdentifier matches *ca_ski*.

    The check compares the first certificate in the PEM file's
    ``AuthorityKeyIdentifier`` extension to the CA's SKI.  Returns
    False on any parse failure or missing extension — treating an
    unreadable leaf as "must regenerate" is the safe default.
    """
    if ca_ski is None:
        return False
    try:
        data = fullchain_path.read_bytes()
        cert = x509.load_pem_x509_certificate(data)
        aki_ext = cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
        aki = aki_ext.value.key_identifier
    except (OSError, ValueError, x509.ExtensionNotFound):
        return False
    return aki == ca_ski


def run(*, force: bool = False) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] %(message)s",
    )
    ca_dir = _default_ca_dir()
    leaves_dir = _default_leaves_dir()
    leaves_dir.mkdir(parents=True, exist_ok=True)

    ca_key, ca_cert = _load_or_create_ca(ca_dir)
    logger.info(
        "CA ready: subject=%s SHA256=%s",
        ca_cert.subject.rfc4514_string(),
        _fingerprint(ca_cert),
    )

    # Publish a copy of the CA at a stable path for web retrieval, plus
    # a plain-text fingerprint for fase's build-time sanity check.
    pub_ca = leaves_dir.parent / "provider_ca.crt"
    pub_ca.parent.mkdir(parents=True, exist_ok=True)
    pub_ca.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    (leaves_dir.parent / "provider_ca_fingerprint.txt").write_text(
        _fingerprint(ca_cert) + "\n",
        encoding="utf-8",
    )

    # Extract the current CA's SubjectKeyIdentifier so we can detect
    # leaves left over from a previous CA generation (e.g. when the
    # leaves-dir volume outlives the CA-dir volume across rebuilds).
    # Chaining fails if the existing leaf's AuthorityKeyIdentifier
    # doesn't match the current CA's SKI — regenerate in that case.
    ca_ski_bytes: bytes | None = None
    try:
        ca_ski_ext = ca_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
        ca_ski_bytes = ca_ski_ext.value.digest
    except x509.ExtensionNotFound:
        ca_ski_bytes = None

    generated = 0
    kept = 0
    stale = 0
    for hostname in PROVIDER_HOSTNAMES:
        host_dir = leaves_dir / hostname
        fullchain = host_dir / "fullchain.pem"
        privkey = host_dir / "privkey.pem"
        if not force and fullchain.exists() and privkey.exists():
            if _leaf_matches_ca(fullchain, ca_ski_bytes):
                kept += 1
                continue
            stale += 1
            logger.info("Leaf for %s signed by a previous CA — regenerating", hostname)
        leaf_key, leaf_cert = _generate_leaf(hostname, ca_key, ca_cert)
        _write_leaf(leaves_dir, hostname, leaf_key, leaf_cert, ca_cert)
        generated += 1
        logger.info("Issued leaf cert for %s", hostname)

    logger.info(
        "Provider cert generation complete: %d issued, %d reused, %d stale (force=%s)",
        generated,
        kept,
        stale,
        force,
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate every leaf cert even if one is present.",
    )
    args = parser.parse_args()
    sys.exit(run(force=bool(args.force)))


if __name__ == "__main__":
    main()
