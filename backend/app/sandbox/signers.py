"""Outbound-webhook signing helpers for phone-provider sandboxes.

Each provider emulator constructs a ``SigningFn`` (see
:mod:`app.sandbox.webhook_raw`) via one of the factories below.  The
returned coroutine takes the current ``(headers, body)`` pair and
returns a new headers dict with the provider-native auth / signature
header attached.

All secrets live on the ``SandboxProvider.credentials`` JSON column —
each factory reads only the fields it needs.

References
----------
* Twilio:      https://www.twilio.com/docs/usage/webhooks/webhooks-security
* Bandwidth:   HTTP Basic auth on callback — the username/password are
               configured on the Messaging/Voice Application.
* Plivo V3:    https://www.plivo.com/docs/sms/concepts/xml-requests/
* Vonage:      Messages API webhooks use a Bearer JWT signed with
               the application's RS256 or Ed25519 private key.
* Telnyx:      Already implemented in ``providers/telnyx/service.py``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any

SigningFn = Callable[[dict[str, str], bytes], Awaitable[dict[str, str]]]


# ── Twilio ────────────────────────────────────────────────────────────────


def make_twilio_signer(
    *,
    auth_token: str,
    url: str,
    form_params: dict[str, Any] | None = None,
) -> SigningFn:
    """Return a signer that attaches ``X-Twilio-Signature``.

    The signing base per Twilio spec is::

        full_url + concat(sorted(form_params, key=k, value=v).items())

    For JSON-body callbacks, Twilio documents an alternate scheme where
    the signing base is ``full_url + sha256(body).hexdigest()`` and the
    client must additionally set the ``X-Twilio-Content-Sha256`` header;
    the outbound voice status callbacks in this sandbox always go out
    as ``application/x-www-form-urlencoded`` so we implement only the
    form variant here — which is also what production fase verifies.
    """
    sorted_pairs = sorted((k, str(v)) for k, v in (form_params or {}).items() if v is not None)
    signing_base = url + "".join(f"{k}{v}" for k, v in sorted_pairs)
    digest = hmac.new(
        auth_token.encode("utf-8"),
        signing_base.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    signature_b64 = base64.b64encode(digest).decode("ascii")

    async def _sign(headers: dict[str, str], body: bytes) -> dict[str, str]:
        del body  # form signature is pre-computed
        merged = dict(headers)
        merged["X-Twilio-Signature"] = signature_b64
        return merged

    return _sign


# ── Bandwidth ─────────────────────────────────────────────────────────────


def make_bandwidth_signer(
    *,
    callback_username: str | None,
    callback_password: str | None,
) -> SigningFn | None:
    """HTTP Basic auth per Bandwidth spec.

    Returns ``None`` when either field is missing — Bandwidth accepts
    unauthenticated callbacks if the application has no creds saved,
    which matches production behaviour on the Bandwidth Dashboard.
    """
    if not callback_username or not callback_password:
        return None
    raw = f"{callback_username}:{callback_password}".encode()
    header = "Basic " + base64.b64encode(raw).decode("ascii")

    async def _sign(headers: dict[str, str], body: bytes) -> dict[str, str]:
        del body
        merged = dict(headers)
        merged["Authorization"] = header
        return merged

    return _sign


# ── Plivo V3 ──────────────────────────────────────────────────────────────


def make_plivo_v3_signer(*, auth_token: str, url: str) -> SigningFn:
    """Plivo V3 signature — ``X-Plivo-Signature-V3`` + nonce.

    Spec: HMAC-SHA256 over ``nonce + "." + url + "." + sha256(body)``,
    Base64-URL-safe encoded.  The ``X-Plivo-Signature-V3-Nonce`` carries
    the random nonce so the receiver can reproduce the signature.
    """

    async def _sign(headers: dict[str, str], body: bytes) -> dict[str, str]:
        nonce = secrets.token_urlsafe(16)
        body_sha = hashlib.sha256(body or b"").hexdigest()
        signing_base = f"{nonce}.{url}.{body_sha}"
        mac = hmac.new(
            auth_token.encode("utf-8"),
            signing_base.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        sig = base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")
        merged = dict(headers)
        merged["X-Plivo-Signature-V3"] = sig
        merged["X-Plivo-Signature-V3-Nonce"] = nonce
        return merged

    return _sign


def verify_plivo_v3_signature(
    *,
    auth_token: str,
    url: str,
    body: bytes,
    nonce: str,
    signature: str,
) -> bool:
    body_sha = hashlib.sha256(body or b"").hexdigest()
    signing_base = f"{nonce}.{url}.{body_sha}"
    mac = hmac.new(
        auth_token.encode("utf-8"),
        signing_base.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected = base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")
    return hmac.compare_digest(expected.encode("ascii"), signature.encode("ascii"))


# ── Vonage Messages API ───────────────────────────────────────────────────


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_vonage_messages_signer(
    *,
    application_id: str,
    private_key_pem: str,
) -> SigningFn:
    """Attach ``Authorization: Bearer <JWT>`` for Vonage webhook calls.

    Vonage Messages API v1 expects the sender to sign each callback
    with the application's private key.  Both RS256 (RSA 2048-bit) and
    Ed25519 are accepted; we detect the key type and pick the matching
    JWS algorithm.  The JWT contains ``iss=application_id``,
    ``jti=random``, ``iat`` + ``exp=iat+900s``.
    """
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives import serialization as _ser
    from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

    key = _ser.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)

    if isinstance(key, rsa.RSAPrivateKey):
        alg = "RS256"
    elif isinstance(key, ed25519.Ed25519PrivateKey):
        alg = "EdDSA"
    else:
        raise ValueError(
            f"Vonage signer requires an RSA or Ed25519 private key; got {type(key).__name__}",
        )

    async def _sign(headers: dict[str, str], body: bytes) -> dict[str, str]:
        del body
        now = int(time.time())
        header = {"typ": "JWT", "alg": alg}
        payload = {
            "iss": application_id,
            "jti": secrets.token_urlsafe(16),
            "iat": now,
            "exp": now + 900,
            "application_id": application_id,
        }
        header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        if alg == "RS256":
            sig = key.sign(  # type: ignore[union-attr]
                signing_input,
                padding.PKCS1v15(),
                _hashes.SHA256(),
            )
        else:  # EdDSA
            sig = key.sign(signing_input)  # type: ignore[union-attr]
        token = f"{header_b64}.{payload_b64}.{_b64url(sig)}"
        merged = dict(headers)
        merged["Authorization"] = f"Bearer {token}"
        return merged

    return _sign


# ── Introspection helpers for tests ──────────────────────────────────────


def compute_twilio_signature(
    *,
    auth_token: str,
    url: str,
    form_params: dict[str, Any] | None,
) -> str:
    sorted_pairs = sorted((k, str(v)) for k, v in (form_params or {}).items() if v is not None)
    signing_base = url + "".join(f"{k}{v}" for k, v in sorted_pairs)
    digest = hmac.new(
        auth_token.encode("utf-8"),
        signing_base.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def admin_token_from_env() -> str | None:
    return os.environ.get("MAILCUE_SANDBOX_ADMIN_TOKEN") or None


__all__ = [
    "SigningFn",
    "admin_token_from_env",
    "compute_twilio_signature",
    "make_bandwidth_signer",
    "make_plivo_v3_signer",
    "make_twilio_signer",
    "make_vonage_messages_signer",
    "verify_plivo_v3_signature",
]
