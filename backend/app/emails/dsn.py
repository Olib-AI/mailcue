"""RFC 3464 delivery status notification parsing.

Every bounce that reaches the server is labelled ground truth about a recipient
that no probe could classify. Catch-all risk scoring is only as good as the
outcomes feeding it, and depending on callers to report outcomes by hand leaves
the model permanently cold. Parsing the notifications the MTA already receives
turns ordinary traffic into training data.

Non-conforming bounces are common enough that a heuristic fallback runs when no
``message/delivery-status`` part is present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from email import message_from_bytes, message_from_string
from email.message import Message
from typing import Literal

Outcome = Literal["delivered", "hard_bounce", "soft_bounce"]

_ADDRESS_TYPE_PREFIX = re.compile(r"^\s*(?:rfc822|x-[\w-]+|local|dns)\s*;\s*", re.IGNORECASE)
_STATUS_REGEX = re.compile(r"\b([245])\.(\d{1,3})\.(\d{1,3})\b")
_SMTP_CODE_REGEX = re.compile(r"\b([245]\d{2})\b")
_ANGLE_ADDRESS = re.compile(r"<([^<>@\s]+@[^<>@\s]+)>")
_BARE_ADDRESS = re.compile(r"\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b")

_FAILURE_PHRASES = (
    "delivery has failed",
    "delivery failed",
    "undeliverable",
    "returned to sender",
    "could not be delivered",
    "delivery status notification (failure)",
    "mail delivery failed",
    "failure notice",
)


@dataclass
class DsnRecipient:
    """One recipient outcome extracted from a delivery status notification."""

    recipient: str
    action: str
    status: str | None = None
    smtp_code: int | None = None
    diagnostic_code: str | None = None
    remote_mta: str | None = None

    @property
    def outcome(self) -> Outcome | None:
        action = self.action.lower()
        status_class = self.status.split(".", 1)[0] if self.status else None
        if action in {"delivered", "relayed", "expanded"}:
            return "delivered"
        if action == "delayed":
            return "soft_bounce"
        if action == "failed":
            if status_class == "5":
                return "hard_bounce"
            if status_class == "4":
                return "soft_bounce"
            if self.smtp_code is not None:
                return "hard_bounce" if self.smtp_code // 100 == 5 else "soft_bounce"
            return "hard_bounce"
        return None


@dataclass
class DsnReport:
    """Parsed delivery status notification."""

    is_dsn: bool = False
    reporting_mta: str | None = None
    original_message_id: str | None = None
    recipients: list[DsnRecipient] = field(default_factory=list)

    @property
    def failures(self) -> list[DsnRecipient]:
        return [item for item in self.recipients if item.outcome in {"hard_bounce", "soft_bounce"}]


def _strip_address_type(value: str) -> str:
    cleaned = _ADDRESS_TYPE_PREFIX.sub("", value.strip())
    cleaned = cleaned.strip().strip("<>").strip()
    return cleaned


def _extract_status(value: str | None) -> str | None:
    if not value:
        return None
    match = _STATUS_REGEX.search(value)
    if not match:
        return None
    return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"


def _extract_smtp_code(diagnostic: str | None) -> int | None:
    if not diagnostic:
        return None
    match = _SMTP_CODE_REGEX.search(diagnostic)
    if not match:
        return None
    return int(match.group(1))


def _normalise_header(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(value.split())
    return collapsed or None


def _delivery_status_blocks(part: Message) -> list[Message]:
    """Return the header blocks of a delivery-status part.

    Python's email parser treats ``message/delivery-status`` as a container and
    exposes each RFC 3464 block as its own ``Message``. Non-conforming senders
    still produce a flat string, so both shapes are handled.
    """
    payload = part.get_payload()
    if isinstance(payload, list):
        return [block for block in payload if isinstance(block, Message)]

    decoded = part.get_payload(decode=True)
    if isinstance(decoded, bytes):
        text = decoded.decode("utf-8", errors="replace")
    elif isinstance(payload, str):
        text = payload
    else:
        return []
    return [
        message_from_string(block)
        for block in re.split(r"\r?\n\s*\r?\n", text.strip())
        if block.strip()
    ]


def _parse_delivery_status(part: Message) -> tuple[str | None, list[DsnRecipient]]:
    """Parse the per-message and per-recipient blocks of a delivery-status part."""
    blocks = _delivery_status_blocks(part)
    if not blocks:
        return None, []

    reporting_mta = _strip_address_type(blocks[0].get("Reporting-MTA", "") or "") or None

    recipients: list[DsnRecipient] = []
    for fields in blocks[1:]:
        raw_recipient = fields.get("Original-Recipient") or fields.get("Final-Recipient")
        if not raw_recipient:
            continue
        recipient = _strip_address_type(_normalise_header(raw_recipient) or "")
        if "@" not in recipient:
            continue
        action = (_normalise_header(fields.get("Action")) or "").strip().lower()
        diagnostic = _normalise_header(fields.get("Diagnostic-Code"))
        status = _extract_status(_normalise_header(fields.get("Status")))
        recipients.append(
            DsnRecipient(
                recipient=recipient,
                action=action or "failed",
                status=status,
                smtp_code=_extract_smtp_code(diagnostic),
                diagnostic_code=diagnostic[:512] if diagnostic else None,
                remote_mta=_strip_address_type(_normalise_header(fields.get("Remote-MTA")) or "")
                or None,
            )
        )
    return reporting_mta, recipients


def _original_message_id(message: Message) -> str | None:
    for part in message.walk():
        content_type = part.get_content_type()
        if content_type in {"message/rfc822", "text/rfc822-headers"}:
            payload = part.get_payload(decode=True)
            inner: Message
            if isinstance(payload, bytes):
                inner = message_from_bytes(payload)
            else:
                nested = part.get_payload()
                if isinstance(nested, list) and nested and isinstance(nested[0], Message):
                    inner = nested[0]
                elif isinstance(nested, str):
                    inner = message_from_string(nested)
                else:
                    continue
            candidate = _normalise_header(inner.get("Message-ID"))
            if candidate:
                return candidate
    return None


def _heuristic_parse(message: Message) -> list[DsnRecipient]:
    """Recover recipients from a bounce that carries no delivery-status part."""
    subject = (_normalise_header(message.get("Subject")) or "").lower()
    body_chunks: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() != "text":
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        body_chunks.append(payload.decode("utf-8", errors="replace"))
    body = "\n".join(body_chunks)
    lowered = f"{subject}\n{body}".lower()
    if not any(phrase in lowered for phrase in _FAILURE_PHRASES):
        return []

    status = _extract_status(body)
    smtp_code = _extract_smtp_code(body)
    if status is None and smtp_code is None:
        return []

    candidates = _ANGLE_ADDRESS.findall(body) or _BARE_ADDRESS.findall(body)
    seen: set[str] = set()
    recipients: list[DsnRecipient] = []
    for candidate in candidates:
        address = candidate.strip().lower()
        local = address.split("@", 1)[0]
        # Postmaster and mailer-daemon addresses belong to the reporting host.
        if local in {"postmaster", "mailer-daemon", "mailerdaemon", "noreply", "no-reply"}:
            continue
        if address in seen:
            continue
        seen.add(address)
        recipients.append(
            DsnRecipient(
                recipient=address,
                action="failed",
                status=status,
                smtp_code=smtp_code,
                diagnostic_code=None,
            )
        )
        if len(recipients) >= 10:
            break
    return recipients


def parse_dsn(raw: bytes | str) -> DsnReport:
    """Parse a raw message into a delivery status report.

    Returns ``is_dsn=False`` for ordinary mail so callers can pass every
    inbound message through without pre-filtering.
    """
    message = message_from_bytes(raw) if isinstance(raw, bytes) else message_from_string(raw)

    report = DsnReport()
    report.original_message_id = _original_message_id(message)

    for part in message.walk():
        if part.get_content_type() == "message/delivery-status":
            reporting_mta, recipients = _parse_delivery_status(part)
            report.is_dsn = True
            report.reporting_mta = report.reporting_mta or reporting_mta
            report.recipients.extend(recipients)

    if report.is_dsn and report.recipients:
        return report

    sender = (_normalise_header(message.get("From")) or "").lower()
    auto_submitted = (_normalise_header(message.get("Auto-Submitted")) or "").lower()
    looks_automated = (
        "mailer-daemon" in sender
        or "postmaster" in sender
        or auto_submitted.startswith("auto-replied")
        or auto_submitted.startswith("auto-generated")
        or report.is_dsn
    )
    if not looks_automated:
        return report

    heuristic = _heuristic_parse(message)
    if heuristic:
        report.is_dsn = True
        report.recipients.extend(heuristic)
    return report
