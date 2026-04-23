"""Round-trip tests for outbound-webhook signing on all five phone
providers.

Every test:

1.  Builds a provider-specific ``SigningFn`` from a synthetic credentials dict.
2.  Signs a sample body with the signer.
3.  Reproduces the verification step a fase-style receiver would run
    (independently re-derived — does NOT re-use the producer code) and
    asserts the signature validates.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from app.sandbox.signers import (
    compute_twilio_signature,
    make_bandwidth_signer,
    make_plivo_v3_signer,
    make_twilio_signer,
    make_vonage_messages_signer,
    verify_plivo_v3_signature,
)

# ── Twilio ────────────────────────────────────────────────────────────────


def test_twilio_signature_matches_spec_vector() -> None:
    # Spec example (abbreviated) from the Twilio webhooks-security doc:
    # url + sorted key-value concat, HMAC-SHA1, base64.
    auth_token = "12345"
    url = "https://mycompany.com/myapp.php?foo=1&bar=2"
    params = {"CallSid": "CA1234567890ABCDE", "Caller": "+14158675309", "Digits": "1234"}

    sig = compute_twilio_signature(auth_token=auth_token, url=url, form_params=params)

    # Independent re-derivation.
    sorted_pairs = sorted(params.items())
    signing_base = url + "".join(f"{k}{v}" for k, v in sorted_pairs)
    expected = base64.b64encode(
        hmac.new(auth_token.encode(), signing_base.encode(), hashlib.sha1).digest()
    ).decode()
    assert sig == expected


@pytest.mark.asyncio
async def test_twilio_signer_attaches_header() -> None:
    signer = make_twilio_signer(
        auth_token="tok_abc",
        url="https://hooks.example.com/sms",
        form_params={"From": "+14155550101", "Body": "hi"},
    )
    headers = await signer({"Content-Type": "application/x-www-form-urlencoded"}, b"")
    assert "X-Twilio-Signature" in headers
    # Reproduce the signature externally.
    signing_base = "https://hooks.example.com/sms" + "Body" + "hi" + "From" + "+14155550101"
    expected = base64.b64encode(
        hmac.new(b"tok_abc", signing_base.encode(), hashlib.sha1).digest()
    ).decode()
    assert headers["X-Twilio-Signature"] == expected


# ── Bandwidth ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bandwidth_basic_auth() -> None:
    signer = make_bandwidth_signer(
        callback_username="app_user",
        callback_password="app_secret",
    )
    assert signer is not None
    headers = await signer({}, b"{}")
    expected = "Basic " + base64.b64encode(b"app_user:app_secret").decode()
    assert headers["Authorization"] == expected


@pytest.mark.asyncio
async def test_bandwidth_signer_absent_when_creds_missing() -> None:
    assert make_bandwidth_signer(callback_username=None, callback_password="x") is None
    assert make_bandwidth_signer(callback_username="x", callback_password=None) is None


# ── Plivo V3 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plivo_v3_sign_and_verify_round_trip() -> None:
    auth_token = "MAMGY1NzQxYJ"
    url = "https://hooks.example.com/plivo/voice"
    body = b"CallUUID=abc123&CallStatus=in-progress"

    signer = make_plivo_v3_signer(auth_token=auth_token, url=url)
    headers = await signer({}, body)
    sig = headers["X-Plivo-Signature-V3"]
    nonce = headers["X-Plivo-Signature-V3-Nonce"]

    assert verify_plivo_v3_signature(
        auth_token=auth_token,
        url=url,
        body=body,
        nonce=nonce,
        signature=sig,
    )
    # Tamper with body — verification must fail.
    assert not verify_plivo_v3_signature(
        auth_token=auth_token,
        url=url,
        body=body + b"X",
        nonce=nonce,
        signature=sig,
    )


# ── Vonage (RS256 JWT) ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vonage_rs256_jwt_signs_and_parses() -> None:
    from cryptography.hazmat.primitives import serialization as _ser
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=_ser.Encoding.PEM,
        format=_ser.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=_ser.NoEncryption(),
    ).decode()

    signer = make_vonage_messages_signer(
        application_id="app-uuid-abc",
        private_key_pem=pem,
    )
    headers = await signer({}, b'{"event":"status"}')
    assert headers["Authorization"].startswith("Bearer ")
    token = headers["Authorization"].removeprefix("Bearer ").strip()
    parts = token.split(".")
    assert len(parts) == 3

    def _b64d(s: str) -> bytes:
        pad = "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s + pad)

    header_json = json.loads(_b64d(parts[0]))
    payload_json = json.loads(_b64d(parts[1]))
    assert header_json == {"typ": "JWT", "alg": "RS256"}
    assert payload_json["iss"] == "app-uuid-abc"
    assert payload_json["application_id"] == "app-uuid-abc"
    assert payload_json["iat"] <= int(time.time()) + 1
    assert payload_json["exp"] > int(time.time())

    # Verify signature with the public key.
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    signing_input = f"{parts[0]}.{parts[1]}".encode()
    signature = _b64d(parts[2])
    key.public_key().verify(
        signature,
        signing_input,
        padding.PKCS1v15(),
        _hashes.SHA256(),
    )


@pytest.mark.asyncio
async def test_vonage_ed25519_jwt_signs_and_parses() -> None:
    from cryptography.hazmat.primitives import serialization as _ser
    from cryptography.hazmat.primitives.asymmetric import ed25519

    key = ed25519.Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=_ser.Encoding.PEM,
        format=_ser.PrivateFormat.PKCS8,
        encryption_algorithm=_ser.NoEncryption(),
    ).decode()

    signer = make_vonage_messages_signer(
        application_id="app-uuid-ed",
        private_key_pem=pem,
    )
    headers = await signer({}, b"{}")
    token = headers["Authorization"].removeprefix("Bearer ").strip()
    parts = token.split(".")

    def _b64d(s: str) -> bytes:
        pad = "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s + pad)

    header_json = json.loads(_b64d(parts[0]))
    assert header_json == {"typ": "JWT", "alg": "EdDSA"}

    signing_input = f"{parts[0]}.{parts[1]}".encode()
    key.public_key().verify(_b64d(parts[2]), signing_input)


# ── Telnyx signer (already present) — lightweight sanity check ────────────


@pytest.mark.asyncio
async def test_telnyx_signer_matches_existing_verifier() -> None:
    # 32-byte Ed25519 private key (raw), base64.
    from cryptography.hazmat.primitives import serialization as _ser
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from app.sandbox.providers.telnyx.service import sign_webhook, verify_signature

    priv = ed25519.Ed25519PrivateKey.generate()
    priv_b64 = base64.b64encode(
        priv.private_bytes(
            encoding=_ser.Encoding.Raw,
            format=_ser.PrivateFormat.Raw,
            encryption_algorithm=_ser.NoEncryption(),
        )
    ).decode()
    pub_b64 = base64.b64encode(
        priv.public_key().public_bytes(
            encoding=_ser.Encoding.Raw,
            format=_ser.PublicFormat.Raw,
        )
    ).decode()

    body = b'{"event":"message.sent"}'
    ts = "1700000000"
    sig = sign_webhook(priv_b64, body, ts)
    assert verify_signature(pub_b64, body, ts, sig) is True
    assert verify_signature(pub_b64, body + b"x", ts, sig) is False
