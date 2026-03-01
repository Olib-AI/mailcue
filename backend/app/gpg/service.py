"""GPG service for key management and cryptographic operations.

Wraps ``python-gnupg`` for all GnuPG interactions.  Blocking GPG calls
are dispatched to a thread via ``asyncio.to_thread`` so the event loop
is never blocked.
"""

from __future__ import annotations

import asyncio
import email as email_stdlib
import json
import logging
import urllib.request
from email import policy
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import gnupg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gpg.models import GpgKey
from app.gpg.schemas import (
    GenerateKeyRequest,
    GpgEmailInfo,
    GpgKeyExportResponse,
    GpgKeyListResponse,
    GpgKeyResponse,
    ImportKeyRequest,
    KeyserverPublishResponse,
    SignatureStatus,
)

logger = logging.getLogger("mailcue.gpg")

# ── GPG instance helper ─────────────────────────────────────────


def _get_gpg() -> gnupg.GPG:
    """Return a ``gnupg.GPG`` instance bound to the configured keyring."""
    return gnupg.GPG(gnupghome=settings.gpg_home)


# ── Key management ───────────────────────────────────────────────


async def generate_key(request: GenerateKeyRequest, db: AsyncSession) -> GpgKeyResponse:
    """Generate a new GPG keypair and persist metadata to the database."""
    gpg = _get_gpg()

    if request.algorithm == "ECC":
        input_data = gpg.gen_key_input(
            key_type="EDDSA",
            key_curve="ed25519",
            subkey_type="ECDH",
            subkey_curve="cv25519",
            name_real=request.name,
            name_email=request.mailbox_address,
            expire_date=request.expire or "0",
            no_protection=True,
        )
    else:
        input_data = gpg.gen_key_input(
            key_type="RSA",
            key_length=request.key_length,
            name_real=request.name,
            name_email=request.mailbox_address,
            expire_date=request.expire or "0",
            no_protection=True,
        )

    key = await asyncio.to_thread(gpg.gen_key, input_data)
    if not key.fingerprint:
        raise ValueError(f"Failed to generate key: {key.stderr}")

    fingerprint = str(key.fingerprint)

    # Export the public key in ASCII armor
    armor = await asyncio.to_thread(gpg.export_keys, fingerprint)

    # Retrieve key metadata from the keyring
    keys = await asyncio.to_thread(gpg.list_keys, False)
    key_info = next((k for k in keys if k["fingerprint"] == fingerprint), None)

    db_key = GpgKey(
        mailbox_address=request.mailbox_address,
        fingerprint=fingerprint,
        key_id=fingerprint[-16:],
        uid_name=request.name,
        uid_email=request.mailbox_address,
        algorithm=key_info.get("algo", request.algorithm) if key_info else request.algorithm,
        key_length=int(key_info.get("length", request.key_length))
        if key_info
        else request.key_length,
        is_private=True,
        public_key_armor=str(armor),
    )
    db.add(db_key)
    await db.commit()
    await db.refresh(db_key)
    return GpgKeyResponse.model_validate(db_key)


async def import_key(request: ImportKeyRequest, db: AsyncSession) -> GpgKeyResponse:
    """Import an armored PGP key and persist metadata to the database."""
    gpg = _get_gpg()
    result = await asyncio.to_thread(gpg.import_keys, request.armored_key)

    if not result.fingerprints:
        raise ValueError(f"Failed to import key: {result.stderr}")

    fingerprint = result.fingerprints[0]

    # Retrieve key details from the keyring
    keys = await asyncio.to_thread(gpg.list_keys, False)
    key_info = next((k for k in keys if k["fingerprint"] == fingerprint), None)

    uid_parts = (
        _parse_uid(key_info["uids"][0]) if key_info and key_info.get("uids") else (None, None)
    )
    address = request.mailbox_address or uid_parts[1] or ""

    db_key = GpgKey(
        mailbox_address=address,
        fingerprint=fingerprint,
        key_id=fingerprint[-16:],
        uid_name=uid_parts[0],
        uid_email=uid_parts[1],
        algorithm=key_info.get("algo") if key_info else None,
        key_length=int(key_info.get("length", 0)) if key_info else None,
        is_private=False,
        public_key_armor=request.armored_key,
    )
    db.add(db_key)
    await db.commit()
    await db.refresh(db_key)
    return GpgKeyResponse.model_validate(db_key)


def _parse_uid(uid: str) -> tuple[str | None, str | None]:
    """Parse a GnuPG UID string like ``Name <email>`` into ``(name, email)``."""
    if "<" in uid and ">" in uid:
        name = uid.split("<")[0].strip()
        email_addr = uid.split("<")[1].split(">")[0].strip()
        return name or None, email_addr or None
    return uid.strip() or None, None


async def list_keys(db: AsyncSession) -> GpgKeyListResponse:
    """Return all active GPG keys from the database."""
    result = await db.execute(
        select(GpgKey).where(GpgKey.is_active == True)  # noqa: E712
    )
    keys = list(result.scalars().all())
    return GpgKeyListResponse(
        keys=[GpgKeyResponse.model_validate(k) for k in keys],
        total=len(keys),
    )


async def get_key_for_address(address: str, db: AsyncSession) -> GpgKeyResponse | None:
    """Look up an active GPG key for the given email address."""
    result = await db.execute(
        select(GpgKey).where(
            GpgKey.mailbox_address == address,
            GpgKey.is_active == True,  # noqa: E712
        )
    )
    key = result.scalars().first()
    if key:
        return GpgKeyResponse.model_validate(key)
    return None


async def export_public_key(address: str, db: AsyncSession) -> GpgKeyExportResponse:
    """Export the ASCII-armored public key for an address."""
    result = await db.execute(
        select(GpgKey).where(
            GpgKey.mailbox_address == address,
            GpgKey.is_active == True,  # noqa: E712
        )
    )
    key = result.scalars().first()
    if not key:
        raise ValueError(f"No key found for {address}")

    if key.public_key_armor:
        armor = key.public_key_armor
    else:
        gpg = _get_gpg()
        armor = str(await asyncio.to_thread(gpg.export_keys, key.fingerprint))

    return GpgKeyExportResponse(
        mailbox_address=address,
        fingerprint=key.fingerprint,
        public_key=armor,
    )


async def delete_key(address: str, db: AsyncSession) -> None:
    """Delete all GPG keys for an address from the keyring and database."""
    result = await db.execute(select(GpgKey).where(GpgKey.mailbox_address == address))
    keys = list(result.scalars().all())
    if not keys:
        raise ValueError(f"No key found for {address}")

    gpg = _get_gpg()
    for key in keys:
        # Secret key must be deleted before the public key
        if key.is_private:
            await asyncio.to_thread(
                gpg.delete_keys, key.fingerprint, True, expect_passphrase=False
            )
        await asyncio.to_thread(gpg.delete_keys, key.fingerprint)
        await db.delete(key)

    await db.commit()


# ── Keyserver publishing ─────────────────────────────────────────

KEYSERVER_UPLOAD_URL = "https://keys.openpgp.org/vks/v1/upload"
KEYSERVER_VERIFY_URL = "https://keys.openpgp.org/vks/v1/request-verify"


def _upload_to_keyserver(armored_key: str) -> dict:
    """Upload an armored public key to keys.openpgp.org (blocking)."""
    req = urllib.request.Request(
        KEYSERVER_UPLOAD_URL,
        data=armored_key.encode("utf-8"),
        headers={"Content-Type": "application/pgp-keys"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _request_verify(token: str, addresses: list[str]) -> dict:
    """Request email verification for published key (blocking)."""
    body = json.dumps({"token": token, "addresses": addresses}).encode()
    req = urllib.request.Request(
        KEYSERVER_VERIFY_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


async def publish_to_keyserver(
    address: str,
    db: AsyncSession,
) -> KeyserverPublishResponse:
    """Publish a GPG public key to keys.openpgp.org.

    Uploads the key and requests email verification so the key becomes
    discoverable by email address on the keyserver.
    """
    export = await export_public_key(address, db)

    # Upload the public key
    try:
        upload_result = await asyncio.to_thread(
            _upload_to_keyserver,
            export.public_key,
        )
    except Exception as exc:
        raise ValueError(f"Failed to upload key to keys.openpgp.org: {exc}") from exc

    token = upload_result.get("token")
    key_fpr = upload_result.get("key_fpr", export.fingerprint)

    # Request email verification so the key is searchable by address
    if token:
        try:
            await asyncio.to_thread(_request_verify, token, [address])
            logger.info(
                "Requested verification for %s on keys.openpgp.org (fpr=%s)",
                address,
                key_fpr,
            )
        except Exception:
            logger.warning(
                "Key uploaded but verification request failed for %s",
                address,
                exc_info=True,
            )
            return KeyserverPublishResponse(
                published=True,
                key_fingerprint=key_fpr,
                message=(
                    f"Key uploaded to keys.openpgp.org but verification "
                    f"request failed. Visit https://keys.openpgp.org to "
                    f"verify {address} manually."
                ),
            )

    return KeyserverPublishResponse(
        published=True,
        key_fingerprint=key_fpr,
        message=(
            f"Key uploaded to keys.openpgp.org. A verification email "
            f"has been sent to {address}. Check the inbox and click the "
            f"link to make the key discoverable by email address."
        ),
    )


# ── Cryptographic operations ─────────────────────────────────────


async def sign_message(raw_bytes: bytes, sender: str, db: AsyncSession) -> bytes:
    """Sign a message using PGP/MIME (RFC 3156 ``multipart/signed``)."""
    key = await get_key_for_address(sender, db)
    if not key or not key.is_private:
        raise ValueError(f"No private key found for {sender}")

    gpg = _get_gpg()

    # Parse the original message
    original = email_stdlib.message_from_bytes(raw_bytes, policy=policy.SMTP)

    # Build the MIME body part that will be signed
    if original.is_multipart():
        content_part = original
    else:
        decoded_payload = original.get_payload(decode=True)
        payload_text = decoded_payload.decode("utf-8", errors="replace") if decoded_payload else ""
        content_part = MIMEText(
            payload_text,
            _subtype=original.get_content_subtype(),
            _charset="utf-8",
        )

    # Serialize content for signing
    content_bytes = content_part.as_bytes()

    # Create a detached signature
    sig = await asyncio.to_thread(
        gpg.sign, content_bytes, keyid=key.fingerprint, detach=True, clearsign=False
    )
    if not sig.data:
        raise ValueError(f"Failed to sign message: {sig.stderr}")

    # Build RFC 3156 multipart/signed structure
    signed_msg = MIMEMultipart(
        "signed",
        protocol="application/pgp-signature",
        micalg="pgp-sha256",
    )

    # Preserve original envelope headers
    for header in ("From", "To", "Cc", "Bcc", "Subject", "Date", "Message-ID", "MIME-Version"):
        value = original[header]
        if value:
            signed_msg[header] = value

    # Part 1: the signed content
    signed_msg.attach(content_part)

    # Part 2: the detached signature
    sig_part = MIMEApplication(
        sig.data,
        _subtype="pgp-signature",
        name="signature.asc",
    )
    sig_part.add_header("Content-Description", "OpenPGP digital signature")
    signed_msg.attach(sig_part)

    return signed_msg.as_bytes()


async def encrypt_message(raw_bytes: bytes, recipients: list[str], db: AsyncSession) -> bytes:
    """Encrypt a message using PGP/MIME (RFC 3156 ``multipart/encrypted``)."""
    # Collect recipient fingerprints
    fingerprints: list[str] = []
    for addr in recipients:
        key = await get_key_for_address(addr, db)
        if not key:
            raise ValueError(f"No public key found for {addr}")
        fingerprints.append(key.fingerprint)

    gpg = _get_gpg()

    # Parse the original message
    original = email_stdlib.message_from_bytes(raw_bytes, policy=policy.SMTP)

    # Build the MIME body to encrypt
    if original.is_multipart():
        body_part = original
    else:
        decoded_payload = original.get_payload(decode=True)
        payload_text = decoded_payload.decode("utf-8", errors="replace") if decoded_payload else ""
        body_part = MIMEText(
            payload_text,
            _subtype=original.get_content_subtype(),
            _charset="utf-8",
        )

    body_bytes = body_part.as_bytes()

    # Encrypt
    encrypted = await asyncio.to_thread(
        gpg.encrypt,
        body_bytes,
        fingerprints,
        always_trust=True,
        armor=True,
    )
    if not encrypted.ok:
        raise ValueError(f"Failed to encrypt message: {encrypted.stderr}")

    # Build RFC 3156 multipart/encrypted structure
    enc_msg = MIMEMultipart(
        "encrypted",
        protocol="application/pgp-encrypted",
    )

    # Preserve original envelope headers
    for header in ("From", "To", "Cc", "Bcc", "Subject", "Date", "Message-ID", "MIME-Version"):
        value = original[header]
        if value:
            enc_msg[header] = value

    # Part 1: PGP/MIME version identification
    version_part = MIMEApplication("Version: 1\n", _subtype="pgp-encrypted")
    version_part.add_header("Content-Description", "PGP/MIME version identification")
    enc_msg.attach(version_part)

    # Part 2: encrypted payload
    data_part = MIMEApplication(str(encrypted), _subtype="octet-stream", name="encrypted.asc")
    data_part.add_header("Content-Description", "OpenPGP encrypted message")
    enc_msg.attach(data_part)

    return enc_msg.as_bytes()


async def verify_signature(raw_bytes: bytes) -> GpgEmailInfo:
    """Verify a PGP/MIME signed message and return verification metadata."""
    import os
    import tempfile

    msg = email_stdlib.message_from_bytes(raw_bytes, policy=policy.SMTP)
    info = GpgEmailInfo(is_signed=True)

    content_type = msg.get_content_type()
    if content_type != "multipart/signed":
        info.is_signed = False
        return info

    parts = list(msg.iter_parts()) if hasattr(msg, "iter_parts") else msg.get_payload()
    if not isinstance(parts, list) or len(parts) < 2:
        info.signature_status = SignatureStatus.error
        return info

    content_part = parts[0]
    sig_part = parts[1]

    content_bytes = content_part.as_bytes()
    sig_payload = sig_part.get_payload(decode=True)
    if sig_payload is None:
        raw_payload = sig_part.get_payload()
        sig_bytes = raw_payload.encode() if isinstance(raw_payload, str) else bytes(raw_payload)
    else:
        sig_bytes = sig_payload

    gpg = _get_gpg()

    # Write the detached signature to a temp file for verify_data()
    sig_fd, sig_path = tempfile.mkstemp(suffix=".sig")
    try:
        os.write(sig_fd, sig_bytes)
        os.close(sig_fd)
        verified = await asyncio.to_thread(gpg.verify_data, sig_path, content_bytes)
    finally:
        os.unlink(sig_path)

    if verified.valid:
        info.signature_status = SignatureStatus.valid
    elif verified.key_id and not verified.valid:
        status_text = (verified.status or "").lower()
        if "expired" in status_text:
            info.signature_status = SignatureStatus.expired_key
        else:
            info.signature_status = SignatureStatus.invalid
    elif verified.status == "no public key":
        info.signature_status = SignatureStatus.no_public_key
    else:
        info.signature_status = SignatureStatus.error

    info.signer_fingerprint = verified.fingerprint or None
    info.signer_key_id = verified.key_id or None
    info.signer_uid = verified.username or None

    return info


async def decrypt_message(raw_bytes: bytes, recipient: str) -> tuple[bytes, GpgEmailInfo]:
    """Decrypt a PGP/MIME encrypted message and return the plaintext."""
    msg = email_stdlib.message_from_bytes(raw_bytes, policy=policy.SMTP)
    info = GpgEmailInfo(is_encrypted=True)

    content_type = msg.get_content_type()
    if content_type != "multipart/encrypted":
        info.is_encrypted = False
        return raw_bytes, info

    parts = list(msg.iter_parts()) if hasattr(msg, "iter_parts") else msg.get_payload()
    if not isinstance(parts, list) or len(parts) < 2:
        info.encryption_key_ids = []
        return raw_bytes, info

    encrypted_part = parts[1]
    enc_payload = encrypted_part.get_payload(decode=True)
    if enc_payload is None:
        raw_payload = encrypted_part.get_payload()
        encrypted_data = (
            raw_payload.encode() if isinstance(raw_payload, str) else bytes(raw_payload)
        )
    else:
        encrypted_data = enc_payload

    gpg = _get_gpg()
    decrypted = await asyncio.to_thread(gpg.decrypt, encrypted_data, always_trust=True)

    if decrypted.ok:
        info.decrypted = True
        info.encryption_key_ids = []

        decrypted_bytes = decrypted.data

        # Reconstruct a complete message: decrypted MIME body + original headers
        original_headers: dict[str, str] = {}
        for header in ("From", "To", "Cc", "Bcc", "Subject", "Date", "Message-ID"):
            value = msg[header]
            if value:
                original_headers[header] = value

        decrypted_msg = email_stdlib.message_from_bytes(decrypted_bytes, policy=policy.SMTP)

        for header, value in original_headers.items():
            if header not in decrypted_msg:
                decrypted_msg[header] = value

        return decrypted_msg.as_bytes(), info

    info.decrypted = False
    return raw_bytes, info
