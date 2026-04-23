"""Telnyx credential helpers and Ed25519 signing."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.sandbox.models import SandboxProvider
from app.sandbox.service import resolve_provider_by_credential

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_bearer(db: AsyncSession, token: str) -> SandboxProvider | None:
    return await resolve_provider_by_credential(db, "telnyx", "api_key", token)


def _generate_keypair() -> tuple[str, str]:
    """Generate a fresh Ed25519 keypair and return (priv_b64, pub_b64)."""
    priv = Ed25519PrivateKey.generate()
    priv_bytes = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return (
        base64.b64encode(priv_bytes).decode(),
        base64.b64encode(pub_bytes).decode(),
    )


def ensure_keypair(provider: SandboxProvider) -> tuple[str, str]:
    """Return (priv_b64, pub_b64) for a provider, generating if missing.

    Mutates ``provider.credentials`` as a side-effect when fresh keys are
    generated; the caller is responsible for committing the session.
    """
    creds = dict(provider.credentials)
    priv_b64 = creds.get("ed25519_private_key")
    pub_b64 = creds.get("ed25519_public_key")
    if priv_b64 and pub_b64:
        return priv_b64, pub_b64
    priv_b64, pub_b64 = _generate_keypair()
    creds["ed25519_private_key"] = priv_b64
    creds["ed25519_public_key"] = pub_b64
    provider.credentials = creds
    return priv_b64, pub_b64


def sign_webhook(priv_b64: str, body: bytes, timestamp: str) -> str:
    """Sign a webhook body with Ed25519 per Telnyx spec.

    Signing base: ``f"{timestamp}|{body.decode()}"`` signed as UTF-8 bytes.
    """
    priv_bytes = base64.b64decode(priv_b64)
    priv = Ed25519PrivateKey.from_private_bytes(priv_bytes)
    signing_base = f"{timestamp}|".encode() + body
    signature = priv.sign(signing_base)
    return base64.b64encode(signature).decode()


def verify_signature(pub_b64: str, body: bytes, timestamp: str, signature_b64: str) -> bool:
    try:
        pub_bytes = base64.b64decode(pub_b64)
        pub = Ed25519PublicKey.from_public_bytes(pub_bytes)
        signing_base = f"{timestamp}|".encode() + body
        pub.verify(base64.b64decode(signature_b64), signing_base)
        return True
    except Exception:
        return False


__all__ = [
    "ensure_keypair",
    "resolve_bearer",
    "sign_webhook",
    "verify_signature",
]
