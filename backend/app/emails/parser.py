"""Raw RFC 5322 email bytes --> structured ``EmailDetail`` conversion.

Uses Python's ``email`` stdlib module with the modern ``email.policy.default``
for correct header decoding and MIME traversal.  Heavy parsing is offloaded
to a thread via ``parse_email_async`` so the event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from io import StringIO
from typing import Any

from app.emails.schemas import AttachmentInfo, EmailDetail, EmailSummary

# ── Public API ───────────────────────────────────────────────────


async def parse_email_async(
    raw: bytes,
    *,
    uid: str = "",
    mailbox: str = "",
) -> EmailDetail:
    """Parse raw email bytes in a background thread and return ``EmailDetail``."""
    return await asyncio.to_thread(parse_email, raw, uid=uid, mailbox=mailbox)


def parse_email(
    raw: bytes,
    *,
    uid: str = "",
    mailbox: str = "",
) -> EmailDetail:
    """Synchronous parser: raw bytes --> ``EmailDetail``."""
    msg = message_from_bytes(raw, policy=policy.default)
    assert isinstance(msg, EmailMessage)

    from_addr = _decode_header_str(msg.get("From", ""))
    to_raw = _decode_header_str(msg.get("To", ""))
    cc_raw = _decode_header_str(msg.get("Cc", ""))
    bcc_raw = _decode_header_str(msg.get("Bcc", ""))
    subject = _decode_header_str(msg.get("Subject", ""))
    date = _parse_date(msg.get("Date"))

    to_addrs = _extract_addresses(to_raw)
    cc_addrs = _extract_addresses(cc_raw)
    bcc_addrs = _extract_addresses(bcc_raw)

    text_body, html_body, attachments = _extract_body_and_attachments(msg)

    headers = _extract_all_headers(msg)
    preview = _make_preview(text_body, html_body)
    has_attachments = len(attachments) > 0

    # Determine read status from IMAP flags (not available in raw parse;
    # caller must set this from IMAP FETCH FLAGS).
    is_read = False

    message_id = _decode_header_str(msg.get("Message-ID", ""))

    # PGP/MIME detection
    is_signed, is_encrypted = _detect_pgp_mime(msg)

    return EmailDetail(
        uid=uid,
        mailbox=mailbox,
        from_address=from_addr,
        to_addresses=to_addrs,
        subject=subject,
        date=date,
        has_attachments=has_attachments,
        is_read=is_read,
        preview=preview,
        message_id=message_id,
        html_body=html_body,
        text_body=text_body,
        cc_addresses=cc_addrs,
        bcc_addresses=bcc_addrs,
        raw_headers=headers,
        attachments=attachments,
        is_signed=is_signed,
        is_encrypted=is_encrypted,
    )


def parse_email_summary(
    raw: bytes,
    *,
    uid: str = "",
    mailbox: str = "",
    is_read: bool = False,
) -> EmailSummary:
    """Quick parse for list views -- avoids full body extraction for performance."""
    msg = message_from_bytes(raw, policy=policy.default)
    assert isinstance(msg, EmailMessage)

    from_addr = _decode_header_str(msg.get("From", ""))
    to_raw = _decode_header_str(msg.get("To", ""))
    subject = _decode_header_str(msg.get("Subject", ""))
    date = _parse_date(msg.get("Date"))
    to_addrs = _extract_addresses(to_raw)

    text_body, html_body, attachments = _extract_body_and_attachments(msg)
    preview = _make_preview(text_body, html_body)

    message_id = _decode_header_str(msg.get("Message-ID", ""))

    # PGP/MIME detection
    is_signed, is_encrypted = _detect_pgp_mime(msg)

    return EmailSummary(
        uid=uid,
        mailbox=mailbox,
        from_address=from_addr,
        to_addresses=to_addrs,
        subject=subject,
        date=date,
        has_attachments=len(attachments) > 0,
        is_read=is_read,
        preview=preview,
        message_id=message_id,
        is_signed=is_signed,
        is_encrypted=is_encrypted,
    )


# ── PGP/MIME detection ───────────────────────────────────────────


def _detect_pgp_mime(msg: EmailMessage) -> tuple[bool, bool]:
    """Detect whether a message uses PGP/MIME signing or encryption.

    Returns ``(is_signed, is_encrypted)`` by inspecting the top-level
    ``Content-Type`` header per RFC 3156.
    """
    content_type = msg.get_content_type()
    params = msg.get_params() or []
    # Flatten params to a dict for easier lookup
    param_dict: dict[str, str] = {}
    for key, value in params:
        param_dict[key.lower()] = value.lower() if isinstance(value, str) else ""

    is_signed = (
        content_type == "multipart/signed"
        and param_dict.get("protocol", "") == "application/pgp-signature"
    )
    is_encrypted = (
        content_type == "multipart/encrypted"
        and param_dict.get("protocol", "") == "application/pgp-encrypted"
    )
    return is_signed, is_encrypted


# ── Internal helpers ─────────────────────────────────────────────


def _decode_header_str(value: Any) -> str:
    """Decode a potentially MIME-encoded header value into a plain string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(make_header(decode_header(str(value))))
    except Exception:
        return str(value)


def _parse_date(raw: Any) -> datetime | None:
    """Parse an RFC 2822 date header into a timezone-aware datetime."""
    if raw is None:
        return None
    try:
        dt = parsedate_to_datetime(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        return None


def _extract_addresses(raw: str) -> list[str]:
    """Extract email addresses from a header value like ``"Name <a@b>, c@d"``."""
    if not raw:
        return []
    pairs = getaddresses([raw])
    return [addr for _name, addr in pairs if addr]


def _extract_body_and_attachments(
    msg: EmailMessage,
) -> tuple[str | None, str | None, list[AttachmentInfo]]:
    """Walk the MIME tree and extract text/html bodies and attachment metadata."""
    text_body: str | None = None
    html_body: str | None = None
    attachments: list[AttachmentInfo] = []
    part_counter = 0

    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition", ""))
        maintype = part.get_content_maintype()

        if maintype == "multipart":
            continue

        payload = part.get_payload(decode=True)
        if payload is None:
            continue

        charset = part.get_content_charset() or "utf-8"
        part_counter += 1

        is_attachment = (
            "attachment" in disposition
            or (part.get_filename() is not None and "inline" not in disposition)
        )

        if is_attachment:
            filename = _decode_header_str(part.get_filename()) or f"attachment_{part_counter}"
            attachments.append(AttachmentInfo(
                filename=filename,
                content_type=content_type,
                size=len(payload),
                part_id=str(part_counter),
            ))
        elif content_type == "text/plain" and text_body is None:
            text_body = _safe_decode(payload, charset)
        elif content_type == "text/html" and html_body is None:
            html_body = _safe_decode(payload, charset)

    return text_body, html_body, attachments


def _safe_decode(payload: bytes, charset: str) -> str:
    """Decode bytes with a fallback chain for broken charsets."""
    for enc in (charset, "utf-8", "latin-1"):
        try:
            return payload.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode("utf-8", errors="replace")


def _extract_all_headers(msg: EmailMessage) -> dict[str, str]:
    """Collect all headers into a flat dict (last value wins for duplicates)."""
    headers: dict[str, str] = {}
    for key in msg:
        headers[key] = _decode_header_str(msg.get(key))
    return headers


class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML-to-text extractor for generating previews."""

    def __init__(self) -> None:
        super().__init__()
        self._result = StringIO()
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._result.write(data)

    def get_text(self) -> str:
        return self._result.getvalue()


def _strip_html(html: str) -> str:
    """Remove HTML tags and return plain text."""
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def _make_preview(text_body: str | None, html_body: str | None, max_length: int = 200) -> str:
    """Generate a short plain-text preview from the best available body."""
    source = text_body if text_body else (_strip_html(html_body) if html_body else "")
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", source).strip()
    if len(clean) > max_length:
        return clean[:max_length] + "..."
    return clean
