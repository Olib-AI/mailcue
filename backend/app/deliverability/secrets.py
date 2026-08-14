"""Domain-separated encryption for deliverability provider credentials."""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings


def _fernet() -> Fernet:
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"mailcue-deliverability-provider-credentials",
        info=b"deliverability-provider-secret-v1",
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(settings.secret_key.encode())))


def encrypt_provider_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_provider_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
