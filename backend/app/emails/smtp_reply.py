"""Provider-aware interpretation of an SMTP RCPT TO response.

A recipient-stage rejection is only useful if it is recognised. Restricting
definitive rejections to the RFC 3463 ``5.1.x`` codes discards the codes the
largest business providers actually use: Microsoft 365 signals Directory Based
Edge Blocking with ``5.4.1`` and Exchange reports ``RESOLVER.ADR.RecipientNotFound``
as ``5.1.10``. Both are conclusive, but ``5.4.1`` is conclusive *only* from a
Microsoft edge, so the enhanced code alone cannot decide it.

Text matching also has to run even when an enhanced code is present, because
many MTAs emit an inaccurate class with an unambiguous phrase after it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.emails.mx_providers import MxProvider

RcptVerdict = Literal["mailbox_absent", "mailbox_present", "temporary", "policy", "unknown"]

ENHANCED_STATUS_REGEX = re.compile(r"\b([245])\.(\d{1,3})\.(\d{1,3})\b")

# Codes that mean "this recipient does not exist" at every MTA.
_UNIVERSAL_ABSENT_CODES = frozenset(
    {
        "5.1.0",  # Other address status, used by Postfix for unknown users
        "5.1.1",  # Bad destination mailbox address
        "5.1.2",  # Bad destination system address
        "5.1.3",  # Bad destination mailbox address syntax
        "5.1.6",  # Mailbox has moved, no forwarding address
        "5.1.10",  # Exchange RESOLVER.ADR.RecipientNotFound
        "5.2.1",  # Mailbox disabled, not accepting messages
    }
)

# Phrases that identify an absent recipient regardless of the enhanced code and
# regardless of any policy wording alongside them.
_STRONG_ABSENT_MARKERS: tuple[str, ...] = (
    "no such user",
    "no such recipient",
    "no such mailbox",
    "no such address",
    "user unknown",
    "unknown user",
    "unknown recipient",
    "unknown mailbox",
    "unknown address",
    "unknown email address",
    "recipient not found",
    "recipient unknown",
    "user not found",
    "mailbox not found",
    "mailbox does not exist",
    "address does not exist",
    "account does not exist",
    "does not exist",
    "invalid recipient",
    "invalid mailbox",
    "recipientnotfound",
    "unrouteable address",
    "unroutable address",
    "not a valid mailbox",
    "no mailbox here by that name",
    "mailbox is disabled",
    "account has been disabled",
    "account is disabled",
    # Non-English receivers still have to be understood.
    "empfänger existiert nicht",
    "unbekannter empfänger",
    "benutzer unbekannt",
    "postfach existiert nicht",
    "destinataire inconnu",
    "destinataire n'existe pas",
    "utilisateur inconnu",
    "adresse inexistante",
    "n'existe pas",
    "usuario desconocido",
    "destinatario desconocido",
    "no existe",
    "utente sconosciuto",
    "destinatario sconosciuto",
    "non esiste",
    "onbekende gebruiker",
    "gebruiker onbekend",
    "bestaat niet",
    "usuário desconhecido",
    "utilizador desconhecido",
    "não existe",
    "nieznany użytkownik",
    "пользователь не найден",
    "адрес не существует",
    "получатель не найден",
    "用户不存在",
    "邮箱不存在",
    "地址不存在",
    "存在しません",
)

# Phrases that usually mean an absent recipient but are also used for policy
# refusals, so a policy marker in the same reply outranks them.
_WEAK_ABSENT_MARKERS: tuple[str, ...] = (
    "recipient rejected",
    "address rejected",
    "invalid address",
    "unknown or illegal alias",
    "account not available",
    "mailbox unavailable",
)

# Phrases that mean the receiver refused us, not the recipient. These must never
# be read as evidence about the mailbox.
_POLICY_MARKERS: tuple[str, ...] = (
    "blocked",
    "blacklist",
    "blocklist",
    "denylist",
    "spamhaus",
    "spam",
    "reputation",
    "policy",
    "rate limit",
    "too many",
    "not authorized",
    "unauthorized",
    "authentication required",
    "relay access denied",
    "relaying denied",
    "access denied",
    "client host rejected",
    "sender rejected",
    "sender verify failed",
    "greylist",
    "try again",
    "temporarily deferred",
)

_REPUTATION_MARKERS: tuple[str, ...] = (
    "blocked",
    "blacklist",
    "blocklist",
    "denylist",
    "spamhaus",
    "spam",
    "reputation",
    "client host rejected",
    "bad reputation",
    "poor reputation",
)


@dataclass(frozen=True)
class RcptClassification:
    """Interpretation of one RCPT TO response."""

    verdict: RcptVerdict
    reason_code: str
    enhanced_status: str | None = None
    # Set when the rejection describes our own sending host rather than the
    # recipient. A probe egress with a reputation problem produces artificial
    # accept-all results, so this has to surface rather than be swallowed.
    sender_reputation_signal: bool = False

    @property
    def is_absent(self) -> bool:
        return self.verdict == "mailbox_absent"

    @property
    def is_present(self) -> bool:
        return self.verdict == "mailbox_present"


def extract_enhanced_status(message: str) -> str | None:
    """Return the RFC 3463 status in a reply line, if one is present."""
    match = ENHANCED_STATUS_REGEX.search(message or "")
    if not match:
        return None
    return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"


def _contains(haystack: str, markers: tuple[str, ...]) -> bool:
    return any(marker in haystack for marker in markers)


def classify_rcpt_response(
    code: int | None,
    message: str | None,
    provider: MxProvider | None = None,
) -> RcptClassification:
    """Classify a RCPT TO reply into a recipient verdict.

    ``provider`` widens the set of definitive codes to the ones that receiver
    is known to use. Without it the classifier stays conservative, because a
    code such as ``5.4.1`` is a missing recipient at Microsoft and an
    unexplained policy refusal almost everywhere else.
    """
    text = (message or "").strip()
    lowered = text.lower()
    enhanced = extract_enhanced_status(text)
    reputation = _contains(lowered, _REPUTATION_MARKERS)

    if code is None:
        return RcptClassification("unknown", "no_smtp_response", enhanced)

    if 200 <= code < 300:
        return RcptClassification("mailbox_present", "mailbox_accepted", enhanced)

    if 400 <= code < 500:
        return RcptClassification(
            "temporary",
            "smtp_temporary_failure",
            enhanced,
            sender_reputation_signal=reputation,
        )

    if not 500 <= code < 600:
        return RcptClassification("unknown", "smtp_unexpected_code", enhanced)

    definitive_codes = set(_UNIVERSAL_ABSENT_CODES)
    if provider is not None:
        definitive_codes |= set(provider.definitive_rejection_codes)

    if enhanced is not None and enhanced in definitive_codes:
        return RcptClassification("mailbox_absent", "mailbox_rejected", enhanced)

    # An accurate phrase outranks an inaccurate class, so text is always
    # consulted even when an enhanced code was parsed.
    if _contains(lowered, _STRONG_ABSENT_MARKERS):
        return RcptClassification("mailbox_absent", "mailbox_rejected", enhanced)

    if _contains(lowered, _POLICY_MARKERS):
        return RcptClassification(
            "policy",
            "sender_blocked" if reputation else "smtp_policy_rejection",
            enhanced,
            sender_reputation_signal=reputation,
        )

    # Reached only when no policy wording accompanies the ambiguous phrase.
    if _contains(lowered, _WEAK_ABSENT_MARKERS):
        return RcptClassification("mailbox_absent", "mailbox_rejected", enhanced)

    return RcptClassification(
        "policy",
        "smtp_policy_rejection",
        enhanced,
        sender_reputation_signal=reputation,
    )
