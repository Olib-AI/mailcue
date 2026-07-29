"""Strict address validation for values used in mail-server configuration."""

from __future__ import annotations

import re

LOCAL_PART_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._+-]{0,62}[A-Za-z0-9])?$")
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def normalize_local_part(value: str) -> str:
    normalized = value.strip().lower()
    if not LOCAL_PART_RE.fullmatch(normalized) or ".." in normalized:
        raise ValueError("Invalid email local part")
    return normalized


def normalize_domain(value: str) -> str:
    normalized = value.strip().lower().rstrip(".")
    if not DOMAIN_RE.fullmatch(normalized):
        raise ValueError("Invalid email domain")
    return normalized


def normalize_email_address(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 254 or normalized.count("@") != 1:
        raise ValueError("Invalid email address")
    local_part, domain = normalized.rsplit("@", 1)
    return f"{normalize_local_part(local_part)}@{normalize_domain(domain)}"
