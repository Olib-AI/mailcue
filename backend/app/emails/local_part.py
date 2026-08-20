"""Risk signals carried by the local part of an address.

Once a destination accepts every recipient, the local part is the only
remaining evidence about whether a mailbox exists. Role accounts are almost
always routed somewhere on an accept-all domain, machine-generated strings
almost never are, and addresses produced by a permutation generator bounce at
far higher rates than addresses that were observed in the wild.

Every signal here is offline and works on an address seen for the first time.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Literal

LocalPartShape = Literal[
    "dotted",
    "underscored",
    "hyphenated",
    "single_token",
    "token_with_digits",
    "initial_prefixed",
    "opaque",
]

# Aliases a domain keeps working even when it has no matching person.
ROLE_ACCOUNTS = frozenset(
    {
        "abuse",
        "accounting",
        "accounts",
        "admin",
        "administrator",
        "billing",
        "careers",
        "compliance",
        "contact",
        "customerservice",
        "enquiries",
        "enquiry",
        "finance",
        "help",
        "helpdesk",
        "hello",
        "hi",
        "hr",
        "info",
        "informacion",
        "inquiries",
        "invoice",
        "invoices",
        "it",
        "jobs",
        "legal",
        "mail",
        "marketing",
        "media",
        "newsletter",
        "no-reply",
        "noc",
        "noreply",
        "office",
        "operations",
        "orders",
        "partners",
        "payments",
        "postmaster",
        "press",
        "privacy",
        "purchasing",
        "recruitment",
        "returns",
        "sales",
        "security",
        "service",
        "shop",
        "support",
        "team",
        "tech",
        "webmaster",
        "welcome",
    }
)

# Addresses that exist in lists as filler rather than as real recipients.
PLACEHOLDER_LOCALS = frozenset(
    {
        "a",
        "aa",
        "aaa",
        "abc",
        "asdf",
        "asdfasdf",
        "demo",
        "dummy",
        "email",
        "emailaddress",
        "example",
        "fake",
        "firstname",
        "foo",
        "foobar",
        "name",
        "none",
        "null",
        "qwerty",
        "sample",
        "test",
        "test1",
        "test123",
        "testing",
        "tester",
        "unknown",
        "user",
        "username",
        "x",
        "xx",
        "xxx",
        "you",
        "your",
        "yourname",
        "youremail",
        "zzz",
    }
)

# Local parts that are far more likely to be a recycled spam trap than a person.
TRAP_MARKERS = frozenset({"spamtrap", "honeypot", "abuse", "postmaster", "spam"})

_VOWELS = frozenset("aeiouyàáâäåæèéêëìíîïòóôöøùúûüÿ")
_HEX_ONLY = re.compile(r"^[0-9a-f]+$")
_TOKEN_SPLIT = re.compile(r"[._\-+]+")
_DIGIT_RUN = re.compile(r"\d+")


@dataclass(frozen=True)
class LocalPartSignals:
    """Offline evidence about one local part."""

    local_part: str
    normalized: str
    shape: LocalPartShape
    is_role_account: bool
    role_name: str | None
    is_placeholder: bool
    is_trap_marker: bool
    has_plus_tag: bool
    gibberish_score: float
    digit_ratio: float
    token_count: int
    # Additive log-odds applied to the base hard-bounce rate for the domain.
    risk_delta: float
    notes: list[str] = field(default_factory=list)


def _strip_plus_tag(local_part: str) -> tuple[str, bool]:
    if "+" in local_part:
        base, _, _tag = local_part.partition("+")
        return base, True
    return local_part, False


def _shape(normalized: str) -> tuple[LocalPartShape, int]:
    tokens = [token for token in _TOKEN_SPLIT.split(normalized) if token]
    count = len(tokens)
    if "." in normalized and count >= 2:
        return "dotted", count
    if "_" in normalized and count >= 2:
        return "underscored", count
    if "-" in normalized and count >= 2:
        return "hyphenated", count
    if count == 1:
        token = tokens[0]
        if any(char.isdigit() for char in token) and any(char.isalpha() for char in token):
            return "token_with_digits", count
        if token.isalpha():
            return "single_token", count
        return "opaque", count
    return "opaque", max(count, 1)


def _gibberish_score(value: str) -> float:
    """Score how unlike a human name a string reads, from 0.0 to 1.0."""
    letters = [char for char in value if char.isalpha()]
    if len(value) < 4:
        return 0.0
    if not letters:
        return 1.0

    score = 0.0
    vowels = sum(1 for char in letters if char in _VOWELS)
    vowel_ratio = vowels / len(letters)
    # Human names in Latin scripts sit roughly between a third and half vowels.
    if vowel_ratio < 0.20:
        score += 0.35
    elif vowel_ratio < 0.28:
        score += 0.15
    elif vowel_ratio > 0.75:
        score += 0.20

    longest_consonant_run = 0
    current = 0
    for char in letters:
        if char in _VOWELS:
            current = 0
        else:
            current += 1
            longest_consonant_run = max(longest_consonant_run, current)
    if longest_consonant_run >= 6:
        score += 0.30
    elif longest_consonant_run >= 5:
        score += 0.15

    compact = _TOKEN_SPLIT.sub("", value)
    if len(compact) >= 12 and _HEX_ONLY.match(compact):
        score += 0.45
    if len(compact) >= 16 and "." not in value and "_" not in value:
        score += 0.15

    # Shannon entropy per character separates a random string from a word.
    counts: dict[str, int] = {}
    for char in compact:
        counts[char] = counts.get(char, 0) + 1
    if compact:
        entropy = -sum((n / len(compact)) * math.log2(n / len(compact)) for n in counts.values())
        if entropy > 3.9 and len(compact) >= 10:
            score += 0.20

    return min(score, 1.0)


def analyze_local_part(local_part: str) -> LocalPartSignals:
    """Derive offline bounce-risk evidence from one local part."""
    raw = (local_part or "").strip()
    base, has_plus_tag = _strip_plus_tag(raw.lower())
    normalized = base

    shape, token_count = _shape(normalized)
    digits = sum(1 for char in normalized if char.isdigit())
    digit_ratio = digits / len(normalized) if normalized else 0.0
    compact = _TOKEN_SPLIT.sub("", normalized)

    is_role_account = normalized in ROLE_ACCOUNTS or compact in ROLE_ACCOUNTS
    role_name = normalized if is_role_account else None
    is_placeholder = normalized in PLACEHOLDER_LOCALS or compact in PLACEHOLDER_LOCALS
    is_trap_marker = any(marker in compact for marker in TRAP_MARKERS)
    gibberish = _gibberish_score(normalized)

    notes: list[str] = []
    delta = 0.0

    if is_role_account:
        # An accept-all domain nearly always routes its role aliases, so these
        # rarely hard bounce. They carry complaint and engagement risk instead,
        # which is a separate decision from deliverability.
        delta -= 0.9
        notes.append(f"Role account '{normalized}' is usually routed on an accept-all domain.")
    if is_placeholder:
        delta += 2.2
        notes.append("Local part is a placeholder rather than a person.")
    if is_trap_marker and not is_role_account:
        delta += 1.2
        notes.append("Local part resembles a spam trap or monitoring address.")
    if gibberish >= 0.6:
        delta += 1.6
        notes.append("Local part looks machine-generated rather than name-like.")
    elif gibberish >= 0.35:
        delta += 0.7
        notes.append("Local part is only weakly name-like.")
    if digit_ratio > 0.5 and len(normalized) >= 6:
        delta += 0.8
        notes.append("Local part is mostly digits.")
    if has_plus_tag:
        delta += 0.3
        notes.append("Sub-addressed local parts are frequently list artefacts.")
    if shape == "dotted" and token_count == 2 and gibberish < 0.35:
        delta -= 0.35
        notes.append("Conventional first.last shape.")
    if len(normalized) <= 2 and not is_role_account:
        delta += 0.9
        notes.append("Local part is unusually short.")

    return LocalPartSignals(
        local_part=raw,
        normalized=normalized,
        shape=shape,
        is_role_account=is_role_account,
        role_name=role_name,
        is_placeholder=is_placeholder,
        is_trap_marker=is_trap_marker,
        has_plus_tag=has_plus_tag,
        gibberish_score=round(gibberish, 3),
        digit_ratio=round(digit_ratio, 3),
        token_count=token_count,
        risk_delta=round(delta, 3),
        notes=notes,
    )


def _name_tokens(normalized: str) -> list[str]:
    return [token for token in _TOKEN_SPLIT.split(_DIGIT_RUN.sub("", normalized)) if token]


def dominant_shape(local_parts: list[str]) -> tuple[LocalPartShape | None, float]:
    """Return the most common shape in a batch and the share of addresses using it."""
    shapes: dict[LocalPartShape, int] = {}
    usable = 0
    for value in local_parts:
        base, _ = _strip_plus_tag((value or "").strip().lower())
        if not base:
            continue
        usable += 1
        shape, _count = _shape(base)
        shapes[shape] = shapes.get(shape, 0) + 1
    if usable == 0 or not shapes:
        return None, 0.0
    best = max(shapes.items(), key=lambda item: item[1])
    return best[0], best[1] / usable


def permutation_clusters(local_parts: list[str]) -> set[str]:
    """Find local parts that look like generated variants of the same person.

    A list containing ``j.smith``, ``jsmith`` and ``john.smith`` at one domain
    was built by expanding a naming convention rather than by observing real
    addresses, and only one of those variants can be the live mailbox.
    """
    by_signature: dict[str, list[str]] = {}
    for value in local_parts:
        base, _ = _strip_plus_tag((value or "").strip().lower())
        tokens = _name_tokens(base)
        if not tokens:
            continue
        letters = "".join(sorted("".join(tokens)))
        if len(letters) < 4:
            continue
        # Variants of one name share their surname, which is the longest token.
        surname = max(tokens, key=len)
        if len(surname) < 4:
            continue
        by_signature.setdefault(surname, []).append(base)

    flagged: set[str] = set()
    for _surname, members in by_signature.items():
        unique = {member for member in members}
        if len(unique) >= 2:
            flagged |= unique
    return flagged
