"""Email business logic -- IMAP fetch, SMTP send, inject, delete.

All IMAP operations authenticate using the Dovecot **master user** so
the API needs only a single credential to access every mailbox:
``user@domain*mailcue-master`` with the master password.
"""

from __future__ import annotations

import contextlib
import email.utils
import logging
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import aioimaplib
import aiosmtplib
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.emails.parser import parse_email_async, parse_email_summary
from app.emails.schemas import (
    BulkInjectRequest,
    BulkInjectResponse,
    EmailDetail,
    EmailListResponse,
    EmailSummary,
    InjectEmailRequest,
    SendEmailRequest,
)
from app.events.bus import event_bus
from app.exceptions import MailServerError, NotFoundError
from app.gpg import service as gpg_service

logger = logging.getLogger("mailcue.emails")


# ── IMAP connection helper ───────────────────────────────────────


async def _imap_connect(mailbox_address: str) -> aioimaplib.IMAP4:
    """Open an authenticated IMAP connection using the Dovecot master user.

    The master user separator is ``*``, so we log in as
    ``user@domain*mailcue-master`` with the master password.
    """
    master_login = f"{mailbox_address}*{settings.imap_master_user}"
    try:
        imap = aioimaplib.IMAP4(host=settings.imap_host, port=settings.imap_port)
        await imap.wait_hello_from_server()
        await imap.login(master_login, settings.imap_master_password)
        return imap
    except Exception as exc:
        raise MailServerError(
            f"Failed to connect to IMAP server for {mailbox_address}: {exc}"
        ) from exc


async def _imap_disconnect(imap: aioimaplib.IMAP4) -> None:
    """Gracefully close an IMAP connection."""
    with contextlib.suppress(Exception):
        await imap.logout()


# ── List emails ──────────────────────────────────────────────────


async def list_emails(
    mailbox: str,
    folder: str = "INBOX",
    page: int = 1,
    per_page: int = 50,
    search: str | None = None,
    sort: str = "date_desc",
) -> EmailListResponse:
    """Fetch a paginated list of email summaries from IMAP.

    Uses IMAP SEARCH for filtering and FETCH for header retrieval.
    Pagination is applied client-side on the UID list (IMAP SORT is
    not universally supported).
    """
    imap = await _imap_connect(mailbox)
    try:
        await imap.select(folder)

        # Build IMAP SEARCH criteria
        criteria = "ALL"
        if search:
            # IMAP TEXT search covers subject + body
            criteria = f'TEXT "{search}"'

        _status_line, data = await imap.uid_search(criteria)
        if not data or not data[0]:
            return EmailListResponse(
                total=0, page=page, page_size=per_page, emails=[], has_more=False
            )

        raw_uids = data[0] if isinstance(data[0], str) else data[0].decode()
        uid_list = raw_uids.split()

        # Reverse for newest-first (default)
        if sort.endswith("desc") or sort == "date_desc":
            uid_list = list(reversed(uid_list))

        total = len(uid_list)
        start = (page - 1) * per_page
        end = start + per_page
        page_uids = uid_list[start:end]

        if not page_uids:
            return EmailListResponse(
                total=total,
                page=page,
                page_size=per_page,
                emails=[],
                has_more=(page * per_page) < total,
            )

        # Fetch headers for the page
        uid_set = ",".join(page_uids)
        _fetch_status, fetch_data = await imap.uid(
            "fetch", uid_set, "(FLAGS BODY.PEEK[HEADER] RFC822.SIZE)"
        )

        items: list[EmailSummary] = []
        current_uid = ""
        current_flags = ""
        for line in fetch_data:
            if isinstance(line, bytes | bytearray):
                decoded = bytes(line).decode("utf-8", errors="replace")
            else:
                decoded = str(line)

            # Detect FETCH response header: "* N FETCH (UID nnn FLAGS (...) ...)"
            if "FETCH" in decoded and "UID" in decoded:
                uid_match = re.search(r"UID\s+(\d+)", decoded)
                flags_match = re.search(r"FLAGS\s+\(([^)]*)\)", decoded)
                if uid_match:
                    current_uid = uid_match.group(1)
                if flags_match:
                    current_flags = flags_match.group(1)
            elif len(decoded) > 50:
                # This is likely the header block
                raw_header = bytes(line) if isinstance(line, bytes | bytearray) else line.encode()
                is_read = "\\Seen" in current_flags
                summary = parse_email_summary(
                    raw_header,
                    uid=current_uid,
                    mailbox=mailbox,
                    is_read=is_read,
                )
                items.append(summary)

        return EmailListResponse(
            total=total,
            page=page,
            page_size=per_page,
            emails=items,
            has_more=(page * per_page) < total,
        )
    finally:
        await _imap_disconnect(imap)


# ── Get single email ─────────────────────────────────────────────


async def get_email(
    mailbox: str,
    uid: str,
    folder: str = "INBOX",
    db: AsyncSession | None = None,
) -> EmailDetail:
    """Fetch the complete email by UID and return a parsed ``EmailDetail``.

    When a ``db`` session is provided, PGP/MIME messages are automatically
    verified (signatures) or decrypted (encrypted) and ``detail.gpg`` is
    populated with the result metadata.
    """
    imap = await _imap_connect(mailbox)
    try:
        await imap.select(folder)
        _status_line, data = await imap.uid("fetch", uid, "(RFC822 FLAGS)")

        raw_bytes = _extract_raw_message(data)
        if raw_bytes is None:
            raise NotFoundError("Email", uid)

        detail = await parse_email_async(raw_bytes, uid=uid, mailbox=mailbox)

        # Determine is_read from FLAGS
        already_read = False
        for line in data:
            text = (
                bytes(line).decode("utf-8", errors="replace")
                if isinstance(line, bytes | bytearray)
                else str(line)
            )
            if "\\Seen" in text:
                already_read = True
                break

        # Mark as read (set \Seen flag) when opening an email
        if not already_read:
            with contextlib.suppress(Exception):
                await imap.uid("store", uid, "+FLAGS", "(\\Seen)")
        detail.is_read = True

        # GPG verification / decryption
        if db is not None:
            if detail.is_signed:
                gpg_info = await gpg_service.verify_signature(raw_bytes)
                detail.gpg = gpg_info
            if detail.is_encrypted:
                decrypted_bytes, gpg_info = await gpg_service.decrypt_message(raw_bytes, mailbox)
                if gpg_info.decrypted:
                    # Re-parse with decrypted content
                    detail = await parse_email_async(decrypted_bytes, uid=uid, mailbox=mailbox)
                    detail.is_read = True
                detail.gpg = gpg_info

        return detail
    finally:
        await _imap_disconnect(imap)


async def get_email_raw(mailbox: str, uid: str, folder: str = "INBOX") -> bytes:
    """Fetch the raw RFC822 bytes for a message."""
    imap = await _imap_connect(mailbox)
    try:
        await imap.select(folder)
        _status_line, data = await imap.uid("fetch", uid, "(RFC822)")

        raw = _extract_raw_message(data)
        if raw is None:
            raise NotFoundError("Email", uid)
        return raw
    finally:
        await _imap_disconnect(imap)


async def get_attachment(
    mailbox: str,
    uid: str,
    part_id: str,
    folder: str = "INBOX",
) -> tuple[bytes, str, str]:
    """Extract a specific MIME part from an email.

    Returns ``(data, content_type, filename)``.
    """
    raw = await get_email_raw(mailbox, uid, folder)
    from email import message_from_bytes
    from email import policy as email_policy

    msg = message_from_bytes(raw, policy=email_policy.default)

    counter = 0
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        counter += 1
        if str(counter) == part_id:
            filename = part.get_filename() or f"attachment_{counter}"
            return payload, part.get_content_type(), filename

    raise NotFoundError("Attachment", part_id)


# ── Send email ───────────────────────────────────────────────────


async def send_email(
    request: SendEmailRequest,
    db: AsyncSession | None = None,
    *,
    sign: bool = False,
    encrypt: bool = False,
) -> str:
    """Send an email via the local SMTP server (Postfix).

    When ``sign`` or ``encrypt`` are ``True`` (and a ``db`` session is
    provided), the message is wrapped in PGP/MIME before delivery.
    """
    # Convert body/body_type to separate fields
    html_body = request.body if request.body_type == "html" else None
    text_body = request.body if request.body_type == "plain" else None

    msg = MIMEMultipart("alternative")
    msg["From"] = request.from_address
    msg["To"] = ", ".join(request.to_addresses)
    if request.cc_addresses:
        msg["Cc"] = ", ".join(request.cc_addresses)
    msg["Subject"] = request.subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=settings.domain)

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    all_recipients = list(request.to_addresses) + list(request.cc_addresses)

    # GPG operations (require a database session for key lookup)
    raw_bytes = msg.as_bytes()
    if db is not None:
        if sign:
            raw_bytes = await gpg_service.sign_message(raw_bytes, request.from_address, db)
        if encrypt:
            raw_bytes = await gpg_service.encrypt_message(raw_bytes, request.to_addresses, db)

    # Re-parse the (potentially GPG-wrapped) message for sending
    final_msg = email.message_from_bytes(raw_bytes)

    try:
        await aiosmtplib.send(
            final_msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            recipients=all_recipients,
            start_tls=False,
            use_tls=False,
        )
    except Exception as exc:
        raise MailServerError(f"SMTP send failed: {exc}") from exc

    message_id: str = msg["Message-ID"]

    # Save a copy to the Sent folder via IMAP APPEND
    try:
        imap = await _imap_connect(request.from_address)
        try:
            # Ensure Sent folder exists
            with contextlib.suppress(Exception):
                await imap.create("Sent")
            await imap.append(
                message_bytes=raw_bytes,
                mailbox="Sent",
                flags="(\\Seen)",
                date=None,
            )
        finally:
            await _imap_disconnect(imap)
    except Exception:
        logger.warning("Could not save sent email to Sent folder for %s", request.from_address)

    await event_bus.publish(
        "email.sent",
        {
            "message_id": message_id,
            "from": request.from_address,
            "to": request.to_addresses,
            "subject": request.subject,
        },
    )

    logger.info("Email sent: %s -> %s", request.from_address, request.to_addresses)
    return message_id


# ── Inject email ─────────────────────────────────────────────────


async def inject_email(
    request: InjectEmailRequest,
    db: AsyncSession | None = None,
    *,
    sign: bool = False,
    encrypt: bool = False,
) -> str:
    """Inject an email directly into a mailbox via IMAP APPEND.

    Builds a raw RFC 5322 message from the request fields and appends
    it to the target mailbox folder.  Includes a synthetic ``Received``
    header so the message appears MTA-delivered.

    When ``sign`` or ``encrypt`` are ``True`` (and a ``db`` session is
    provided), the message is wrapped in PGP/MIME before injection.
    """
    raw = _build_raw_email(request)

    # GPG operations (require a database session for key lookup)
    if db is not None:
        if sign:
            raw = await gpg_service.sign_message(raw, request.from_address, db)
        if encrypt:
            raw = await gpg_service.encrypt_message(raw, request.to_addresses, db)

    imap = await _imap_connect(request.mailbox)

    try:
        await imap.select("INBOX")
        _status_line, data = await imap.append(
            message_bytes=raw,
            mailbox="INBOX",
            flags=None,
            date=None,
        )

        # Parse the APPENDUID response to get the new UID
        uid_str = "unknown"
        if data:
            for item in data:
                text = bytes(item).decode() if isinstance(item, bytes | bytearray) else str(item)
                if "APPENDUID" in text.upper():
                    match = re.search(r"APPENDUID\s+\d+\s+(\d+)", text, re.IGNORECASE)
                    if match:
                        uid_str = match.group(1)
                        break

        await event_bus.publish(
            "email.received",
            {
                "mailbox": request.mailbox,
                "uid": uid_str,
                "from": request.from_address,
                "subject": request.subject,
            },
        )

        logger.info("Email injected into %s (uid=%s)", request.mailbox, uid_str)
        return uid_str
    finally:
        await _imap_disconnect(imap)


async def bulk_inject(request: BulkInjectRequest) -> BulkInjectResponse:
    """Inject multiple emails sequentially."""
    injected = 0
    failed = 0
    ids: list[str] = []

    for inject_req in request.emails:
        try:
            uid = await inject_email(inject_req)
            ids.append(uid)
            injected += 1
        except Exception:
            logger.exception("Failed to inject email into %s", inject_req.mailbox)
            failed += 1

    return BulkInjectResponse(injected=injected, failed=failed, ids=ids)


# ── Delete email ─────────────────────────────────────────────────


async def delete_email(mailbox: str, uid: str, folder: str = "INBOX") -> None:
    """Move an email to Trash, or permanently delete if already in Trash."""
    imap = await _imap_connect(mailbox)
    try:
        await imap.select(folder)

        if folder.lower() == "trash":
            # Already in Trash — permanently delete
            await imap.uid("store", uid, "+FLAGS", "(\\Deleted)")
            await imap.expunge()
            logger.info("Email permanently deleted: %s/Trash uid=%s", mailbox, uid)
        else:
            # Move to Trash (COPY then DELETE from source)
            # Ensure Trash folder exists
            with contextlib.suppress(Exception):
                await imap.create("Trash")
            await imap.uid("copy", uid, "Trash")
            await imap.uid("store", uid, "+FLAGS", "(\\Deleted)")
            await imap.expunge()
            logger.info("Email moved to Trash: %s/%s uid=%s", mailbox, folder, uid)

        await event_bus.publish(
            "email.deleted",
            {
                "mailbox": mailbox,
                "uid": uid,
            },
        )
    finally:
        await _imap_disconnect(imap)


# ── Search ───────────────────────────────────────────────────────


async def search_emails(
    mailbox: str,
    query: str,
    folder: str = "INBOX",
) -> list[str]:
    """Return a list of UIDs matching the IMAP TEXT search."""
    imap = await _imap_connect(mailbox)
    try:
        await imap.select(folder)
        _status_line, data = await imap.uid_search(f'TEXT "{query}"')
        if not data or not data[0]:
            return []
        raw = data[0] if isinstance(data[0], str) else data[0].decode()
        return raw.split()
    finally:
        await _imap_disconnect(imap)


# ── Internal helpers ─────────────────────────────────────────────


def _build_raw_email(request: InjectEmailRequest) -> bytes:
    """Construct raw RFC 5322 bytes from an ``InjectEmailRequest``."""
    msg = MIMEMultipart("alternative")
    msg["From"] = request.from_address
    msg["To"] = ", ".join(request.to_addresses)
    msg["Subject"] = request.subject

    # Use specified date or current time
    if request.date:
        msg["Date"] = email.utils.format_datetime(request.date)
    else:
        msg["Date"] = email.utils.formatdate(localtime=True)

    msg["Message-ID"] = email.utils.make_msgid(domain=settings.domain)

    # Synthetic Received header so the message appears MTA-delivered
    now = email.utils.formatdate(localtime=True)
    msg["Received"] = (
        f"from mailcue-inject (localhost [127.0.0.1]) "
        f"by {settings.domain} (MailCue) with ESMTP; {now}"
    )

    # Custom headers
    for key, value in request.headers.items():
        msg[key] = value

    if request.text_body:
        msg.attach(MIMEText(request.text_body, "plain", "utf-8"))
    if request.html_body:
        msg.attach(MIMEText(request.html_body, "html", "utf-8"))

    # If neither body was provided, add an empty text part
    if not request.text_body and not request.html_body:
        msg.attach(MIMEText("", "plain", "utf-8"))

    return msg.as_bytes()


def _extract_raw_message(data: list[Any]) -> bytes | None:
    """Extract the raw message bytes from an IMAP FETCH response."""
    for item in data:
        if isinstance(item, bytes | bytearray) and len(item) > 100 and bytes(item) != b")":
            return bytes(item)
        if isinstance(item, tuple):
            for sub_item in item:
                if isinstance(sub_item, bytes | bytearray) and len(sub_item) > 100:
                    return bytes(sub_item)
    return None
