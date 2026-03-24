"""Email business logic -- IMAP fetch, SMTP send, inject, delete.

All IMAP operations authenticate using the Dovecot **master user** so
the API needs only a single credential to access every mailbox:
``user@domain*mailcue-master`` with the master password.
"""

from __future__ import annotations

import base64
import contextlib
import email.utils
import html as html_module
import logging
import re
import secrets
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import aioimaplib
import aiosmtplib
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.emails.parser import parse_email_async, parse_email_summary
from app.emails.schemas import (
    BulkDeleteRequest,
    BulkDeleteResponse,
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
        logger.error("Failed to connect to IMAP server for %s: %s", mailbox_address, exc)
        raise MailServerError("Mail server unavailable. Please try again later.") from exc


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

        items_by_uid: dict[str, EmailSummary] = {}
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
                items_by_uid[current_uid] = summary

        # Re-sort items to match the requested page_uids order (IMAP FETCH
        # returns results in ascending UID order regardless of request order).
        items = [items_by_uid[u] for u in page_uids if u in items_by_uid]

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
    if request.from_name:
        msg["From"] = email.utils.formataddr((request.from_name, request.from_address))
    else:
        msg["From"] = request.from_address
    msg["To"] = ", ".join(request.to_addresses)
    if request.cc_addresses:
        msg["Cc"] = ", ".join(request.cc_addresses)
    msg["Subject"] = request.subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=settings.domain)
    msg["X-Mailer"] = "MailCue/1.0"
    if request.reply_to:
        msg["Reply-To"] = request.reply_to
    if request.in_reply_to:
        msg["In-Reply-To"] = request.in_reply_to
    if request.references:
        msg["References"] = " ".join(request.references)

    # Always include both text/plain and text/html for best deliverability.
    # Gmail and other providers penalize emails that lack a text/plain part.
    if html_body and not text_body:
        # Strip HTML tags to generate a plain-text fallback
        plain = re.sub(r"<[^>]+>", "", html_module.unescape(html_body)).strip()
        msg.attach(MIMEText(plain, "plain", "utf-8"))
    elif text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        # Close void HTML elements for XHTML compliance (<br>, <hr>, <img>)
        html_body = re.sub(r"<(br|hr|img)(\s[^>]*)?\s*/?>", r"<\1\2 />", html_body)
        # Wrap in a proper XHTML document if not already wrapped
        if "<html" not in html_body.lower():
            html_body = (
                "<!DOCTYPE html>\n"
                '<html lang="en" xmlns="http://www.w3.org/1999/xhtml">\n'
                "<head>\n"
                '  <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />\n'
                '  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
                "  <title></title>\n"
                "</head>\n"
                "<body>\n" + html_body + "\n</body>\n</html>"
            )
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    # List-Unsubscribe header (improves deliverability scores)
    unsub_addr = f"unsubscribe@{settings.domain}"
    msg["List-Unsubscribe"] = f"<mailto:{unsub_addr}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

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
        logger.error("SMTP send failed: %s", exc)
        raise MailServerError("Failed to send email. Please try again later.") from exc

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


async def bulk_delete_emails(
    mailbox: str, request: BulkDeleteRequest, folder: str = "INBOX"
) -> BulkDeleteResponse:
    """Delete multiple emails by UID from a mailbox."""
    deleted = 0
    failed = 0
    for uid in request.uids:
        try:
            await delete_email(mailbox=mailbox, uid=uid, folder=folder)
            deleted += 1
        except Exception:
            logger.exception("Failed to delete email uid=%s from %s", uid, mailbox)
            failed += 1
    return BulkDeleteResponse(deleted=deleted, failed=failed)


async def purge_mailbox(mailbox: str) -> int:
    """Delete ALL emails from every folder in a mailbox. Returns count deleted."""
    from app.mailboxes.service import _imap_get_folder_stats

    folders = await _imap_get_folder_stats(mailbox)
    total_deleted = 0

    for folder_info in folders:
        if folder_info.message_count == 0:
            continue
        imap = await _imap_connect(mailbox)
        try:
            await imap.select(folder_info.name)
            _status, data = await imap.uid_search("ALL")
            if not data or not data[0]:
                continue
            raw_uids = data[0] if isinstance(data[0], str) else data[0].decode()
            uid_list = raw_uids.split()
            if not uid_list:
                continue
            uid_set = ",".join(uid_list)
            await imap.uid("store", uid_set, "+FLAGS", "(\\Deleted)")
            await imap.expunge()
            total_deleted += len(uid_list)
        finally:
            await _imap_disconnect(imap)

    if total_deleted > 0:
        await event_bus.publish(
            "email.deleted",
            {"mailbox": mailbox, "uid": "*", "purged": total_deleted},
        )

    logger.info("Purged %d emails from mailbox %s", total_deleted, mailbox)
    return total_deleted


# ── Flag management ──────────────────────────────────────────


async def set_email_flags(
    mailbox: str,
    uid: str,
    *,
    seen: bool,
    folder: str = "INBOX",
) -> None:
    """Set or clear the ``\\Seen`` flag on an email.

    Uses IMAP ``UID STORE`` with ``+FLAGS`` or ``-FLAGS`` to toggle
    the read/unread state without modifying other flags.
    """
    imap = await _imap_connect(mailbox)
    try:
        await imap.select(folder)
        action = "+FLAGS" if seen else "-FLAGS"
        await imap.uid("store", uid, action, "(\\Seen)")
        logger.info(
            "Email flags updated: %s/%s uid=%s seen=%s",
            mailbox,
            folder,
            uid,
            seen,
        )
    finally:
        await _imap_disconnect(imap)


# ── Search ───────────────────────────────────────────────────────


async def move_email_to_folder(
    mailbox: str,
    uid: str,
    source_folder: str,
    target_folder: str,
) -> None:
    """Move an email between IMAP folders via COPY + DELETE.

    Selects the *source_folder*, copies the message identified by *uid*
    to *target_folder*, marks the original as ``\\Deleted``, and expunges.
    The target folder is created if it does not already exist.
    """
    imap = await _imap_connect(mailbox)
    try:
        await imap.select(source_folder)

        # Ensure the target folder exists
        with contextlib.suppress(Exception):
            await imap.create(target_folder)

        await imap.uid("copy", uid, target_folder)
        await imap.uid("store", uid, "+FLAGS", "(\\Deleted)")
        await imap.expunge()

        logger.info(
            "Email moved: %s uid=%s %s -> %s",
            mailbox,
            uid,
            source_folder,
            target_folder,
        )
    finally:
        await _imap_disconnect(imap)


async def train_spam(
    mailbox: str,
    uid: str,
    folder: str,
    *,
    is_spam: bool,
) -> None:
    """Placeholder for SpamAssassin ``sa-learn`` training.

    In a production deployment this would fetch the raw RFC 822 message
    and pipe it through ``sa-learn --spam`` or ``sa-learn --ham``.
    For now the action is only logged.
    """
    action = "spam" if is_spam else "ham"
    logger.info(
        "Spam training requested (no-op): mailbox=%s uid=%s folder=%s action=%s",
        mailbox,
        uid,
        folder,
        action,
    )


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


def _generate_realistic_headers(
    msg: MIMEMultipart,
    request: InjectEmailRequest,
) -> None:
    """Add realistic email provider headers to a MIME message.

    Generates multi-hop Received chains, authentication results,
    ARC headers, and a simulated DKIM signature so injected emails
    are indistinguishable from real MTA-delivered messages.
    """
    from_domain = request.from_address.split("@")[1]
    to_address = request.to_addresses[0] if request.to_addresses else request.mailbox
    domain = settings.domain
    now_ts = int(time.time())
    now_rfc = email.utils.formatdate(now_ts, localtime=True)
    minus_1s = email.utils.formatdate(now_ts - 1, localtime=True)
    minus_2s = email.utils.formatdate(now_ts - 2, localtime=True)

    # Helper for realistic-looking base64 strings
    def _b64_token(nbytes: int = 32) -> str:
        return base64.b64encode(secrets.token_bytes(nbytes)).decode()

    # ── Received headers (most recent first — 3 hops) ────────────
    msg["Received"] = (
        f"from edge-proxy-42.mailcue.net (edge-proxy-42.mailcue.net [10.128.0.42])\r\n"
        f"\tby mx1.{domain} (MailCue MTA 1.0) with ESMTPS id {secrets.token_hex(8)}\r\n"
        f"\tfor <{to_address}>; {now_rfc}"
    )
    msg["Received"] = (
        f"from smtp-out-01.mailcue.net (smtp-out-01.mailcue.net [10.64.1.1])\r\n"
        f"\tby edge-proxy-42.mailcue.net (MailCue Edge 1.0) with ESMTP id {secrets.token_hex(8)};\r\n"
        f"\t{minus_1s}"
    )
    msg["Received"] = (
        f"from [192.168.1.100] (client-host.example.com [203.0.113.42])\r\n"
        f"\tby smtp-out-01.mailcue.net (MailCue Submission 1.0) with ESMTPSA id {secrets.token_hex(8)}\r\n"
        f"\t(version=TLSv1.3 cipher=TLS_AES_256_GCM_SHA384 bits=256/256);\r\n"
        f"\t{minus_2s}"
    )

    # ── Authentication-Results ────────────────────────────────────
    short_sig = _b64_token(6)[:8]
    msg["Authentication-Results"] = (
        f"mx1.{domain};\r\n"
        f"\tdkim=pass header.d={from_domain} header.s=mail header.b={short_sig};\r\n"
        f"\tspf=pass (mailcue: domain of {request.from_address} designates 203.0.113.42 as permitted sender)"
        f" smtp.mailfrom={request.from_address};\r\n"
        f"\tdmarc=pass (p=QUARANTINE sp=QUARANTINE dis=NONE) header.from={from_domain}"
    )

    # ── ARC headers (RFC 8617) ────────────────────────────────────
    year = time.strftime("%Y")
    arc_b64 = _b64_token(48)
    body_hash = _b64_token(32)
    sig_placeholder = _b64_token(48)

    msg["ARC-Seal"] = (
        f"i=1; a=rsa-sha256; t={now_ts}; cv=none;\r\n\td={domain}; s=arc-{year};\r\n\tb={arc_b64}"
    )
    msg["ARC-Message-Signature"] = (
        f"i=1; a=rsa-sha256; c=relaxed/relaxed;\r\n"
        f"\td={domain}; s=arc-{year}; t={now_ts};\r\n"
        f"\th=from:to:subject:date:message-id;\r\n"
        f"\tbh={body_hash};\r\n"
        f"\tb={sig_placeholder}"
    )
    msg["ARC-Authentication-Results"] = (
        f"i=1; mx1.{domain};\r\n"
        f"\tdkim=pass header.d={from_domain};\r\n"
        f"\tspf=pass smtp.mailfrom={request.from_address};\r\n"
        f"\tdmarc=pass header.from={from_domain}"
    )

    # ── DKIM-Signature (simulated for inject path) ────────────────
    dkim_body_hash = _b64_token(32)
    dkim_sig = _b64_token(64)
    msg["DKIM-Signature"] = (
        f"v=1; a=rsa-sha256; c=relaxed/relaxed;\r\n"
        f"\td={from_domain}; s=mail; t={now_ts};\r\n"
        f"\th=from:to:subject:date:message-id:content-type:mime-version;\r\n"
        f"\tbh={dkim_body_hash};\r\n"
        f"\tb={dkim_sig}"
    )

    # ── Standard headers ──────────────────────────────────────────
    msg["Return-Path"] = f"<{request.return_path or request.from_address}>"
    msg["X-Mailer"] = "MailCue/1.0"
    msg["X-Originating-IP"] = "[203.0.113.42]"

    if request.reply_to:
        msg["Reply-To"] = request.reply_to
    if request.in_reply_to:
        msg["In-Reply-To"] = request.in_reply_to
    if request.references:
        msg["References"] = " ".join(request.references)
    if request.cc_addresses:
        msg["Cc"] = ", ".join(request.cc_addresses)


def _build_raw_email(request: InjectEmailRequest) -> bytes:
    """Construct raw RFC 5322 bytes from an ``InjectEmailRequest``.

    When ``request.realistic_headers`` is ``True``, the message is
    enriched with multi-hop Received chains, authentication results,
    ARC headers, and a simulated DKIM signature so it looks like a
    genuine MTA-delivered email.
    """
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

    if request.realistic_headers:
        _generate_realistic_headers(msg, request)
    else:
        # Basic Received header for backward compatibility
        now = email.utils.formatdate(localtime=True)
        msg["Received"] = (
            f"from mailcue-inject (localhost [127.0.0.1]) "
            f"by {settings.domain} (MailCue) with ESMTP; {now}"
        )

    # Custom headers (applied last so they can override generated ones)
    for key, value in request.headers.items():
        # Remove existing header if present so the custom value wins
        if key in msg:
            del msg[key]
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
