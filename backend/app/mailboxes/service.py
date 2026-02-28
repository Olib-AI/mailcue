"""Mailbox business logic -- CRUD, Dovecot provisioning, Maildir creation."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.events.bus import event_bus
from app.exceptions import ConflictError, MailServerError, NotFoundError
from app.mailboxes.models import Mailbox
from app.mailboxes.schemas import FolderInfo, MailboxCreateRequest, MailboxStats

logger = logging.getLogger("mailcue.mailboxes")


# ── Public API ───────────────────────────────────────────────────


async def sync_filesystem_mailboxes(db: AsyncSession) -> None:
    """Scan the Maildir filesystem and register any undiscovered mailboxes in the DB.

    This is essential for catch-all support: emails arrive for arbitrary
    addresses (e.g. user222@gmail.com) and Dovecot auto-creates Maildirs,
    but the API only lists mailboxes from the database.  This function
    bridges that gap by scanning ``/var/mail/vhosts/{domain}/{user}/``
    and inserting missing ``Mailbox`` rows.
    """
    vhosts = Path(settings.mail_storage_path)
    if not vhosts.is_dir():
        return

    # Collect all existing addresses from the DB for fast lookup
    stmt = select(Mailbox.address)
    result = await db.execute(stmt)
    known_addresses: set[str] = {row[0] for row in result.all()}

    new_count = 0
    for domain_dir in vhosts.iterdir():
        if not domain_dir.is_dir():
            continue
        domain = domain_dir.name
        for user_dir in domain_dir.iterdir():
            if not user_dir.is_dir():
                continue
            local_part = user_dir.name
            address = f"{local_part}@{domain}"
            if address in known_addresses:
                continue
            # Check it's actually a Maildir (has cur/new/tmp subdirs)
            if not (user_dir / "cur").is_dir():
                continue
            mailbox = Mailbox(
                address=address,
                display_name=local_part,
                domain=domain,
            )
            db.add(mailbox)
            known_addresses.add(address)
            new_count += 1

    if new_count > 0:
        await db.commit()
        logger.info("Auto-discovered %d mailbox(es) from filesystem.", new_count)


async def list_mailboxes(db: AsyncSession) -> list[Mailbox]:
    """Return all active mailboxes ordered by creation date."""
    # Sync filesystem-discovered mailboxes first (catch-all support)
    await sync_filesystem_mailboxes(db)
    stmt = select(Mailbox).where(Mailbox.is_active.is_(True)).order_by(Mailbox.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_mailbox(mailbox_id: str, db: AsyncSession) -> Mailbox:
    """Fetch a single mailbox by ID or raise ``NotFoundError``."""
    mailbox = await db.get(Mailbox, mailbox_id)
    if mailbox is None or not mailbox.is_active:
        raise NotFoundError("Mailbox", mailbox_id)
    return mailbox


async def get_mailbox_by_address(address: str, db: AsyncSession) -> Mailbox:
    """Fetch a mailbox by its email address or raise ``NotFoundError``."""
    stmt = select(Mailbox).where(Mailbox.address == address.lower())
    result = await db.execute(stmt)
    mailbox = result.scalar_one_or_none()
    if mailbox is None:
        raise NotFoundError("Mailbox", address)
    return mailbox


async def create_mailbox(
    body: MailboxCreateRequest,
    db: AsyncSession,
) -> Mailbox:
    """Create a mailbox in the database and provision it on the mail server.

    Steps:
    1. Insert a ``Mailbox`` row into SQLite.
    2. Append a line to the Dovecot ``passwd-file``.
    3. Create the Maildir directory structure.
    4. Publish an SSE ``mailbox.created`` event.
    """
    domain = (body.domain or settings.domain).lower()
    local_part = body.username.lower()
    address = f"{local_part}@{domain}"

    # Check uniqueness
    stmt = select(Mailbox).where(Mailbox.address == address)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise ConflictError(f"Mailbox '{address}' already exists")

    # 1. Database record
    mailbox = Mailbox(
        address=address,
        display_name=body.display_name or local_part,
        domain=domain,
    )
    db.add(mailbox)
    await db.commit()
    await db.refresh(mailbox)

    # 2 + 3. System provisioning (blocking I/O in thread pool)
    try:
        await _provision_system_mailbox(address, body.password, domain, local_part)
    except Exception as exc:
        logger.exception("Failed to provision system mailbox for %s", address)
        # Roll back the DB record so we stay consistent
        await db.delete(mailbox)
        await db.commit()
        raise MailServerError(
            f"Failed to provision mailbox '{address}' on the mail server"
        ) from exc

    # 4. SSE event
    await event_bus.publish(
        "mailbox.created",
        {
            "id": mailbox.id,
            "address": mailbox.address,
        },
    )

    logger.info("Mailbox '%s' created.", address)
    return mailbox


async def delete_mailbox(
    mailbox_id: str,
    db: AsyncSession,
    *,
    remove_maildir: bool = False,
) -> None:
    """Soft-delete a mailbox and remove it from Dovecot.

    Steps:
    1. Mark the ``Mailbox`` row inactive.
    2. Remove the line from the Dovecot ``passwd-file``.
    3. Optionally remove the Maildir directory.
    4. Publish an SSE ``mailbox.deleted`` event.
    """
    mailbox = await db.get(Mailbox, mailbox_id)
    if mailbox is None:
        raise NotFoundError("Mailbox", mailbox_id)

    address = mailbox.address
    local_part, domain = address.split("@", maxsplit=1)

    # 1. Soft delete in DB
    mailbox.is_active = False
    await db.commit()

    # 2. Remove from Dovecot users file
    try:
        await _remove_from_dovecot_users(address)
    except Exception:
        logger.exception("Failed to remove %s from Dovecot users file", address)

    # 3. Optionally remove Maildir
    if remove_maildir:
        maildir = Path(settings.mail_storage_path) / domain / local_part
        try:
            await asyncio.to_thread(_remove_directory_tree, maildir)
        except Exception:
            logger.exception("Failed to remove Maildir for %s", address)

    # 4. SSE event
    await event_bus.publish(
        "mailbox.deleted",
        {
            "id": mailbox.id,
            "address": address,
        },
    )

    logger.info("Mailbox '%s' deleted.", address)


async def get_mailbox_stats(mailbox_id: str, db: AsyncSession) -> MailboxStats:
    """Retrieve message counts for a mailbox via IMAP STATUS.

    Falls back to zeroed stats when the mail server is unreachable.
    """
    mailbox = await get_mailbox(mailbox_id, db)

    try:
        folders = await _imap_get_folder_stats(mailbox.address)
    except Exception:
        logger.warning("IMAP unreachable for stats on %s; returning zeroes.", mailbox.address)
        folders = [FolderInfo(name="INBOX", message_count=0, unseen_count=0)]

    total_emails = sum(f.message_count for f in folders)
    unread_emails = sum(f.unseen_count for f in folders)

    return MailboxStats(
        mailbox_id=mailbox.id,
        address=mailbox.address,
        total_emails=total_emails,
        unread_emails=unread_emails,
        total_size_bytes=0,  # Requires QUOTA extension; defer
        folders=folders,
    )


# ── Internal helpers ─────────────────────────────────────────────


async def _provision_system_mailbox(
    address: str,
    password: str,
    domain: str,
    local_part: str,
) -> None:
    """Create the Dovecot user entry, Maildir structure, and Postfix maps on disk."""
    maildir = Path(settings.mail_storage_path) / domain / local_part

    # Create Maildir structure
    await asyncio.to_thread(_create_maildir, maildir)

    # Hash the password for Dovecot (SHA512-CRYPT via doveadm if available,
    # otherwise fall back to Argon2 which Dovecot 2.4+ supports).
    hashed = await asyncio.to_thread(_dovecot_hash_password, password)

    # Append to passwd-file
    # Format: user@domain:{SCHEME}hash:uid:gid::home::
    user_line = f"{address}:{hashed}:5000:5000::{maildir}::\n"
    await asyncio.to_thread(_append_to_file, Path(settings.dovecot_users_file), user_line)

    # Append to Postfix virtual_mailboxes for backward compat (catch-all
    # makes this optional, so failures are non-fatal).
    try:
        postfix_line = f"{address}    {domain}/{local_part}/\n"
        await asyncio.to_thread(
            _append_to_file, Path("/etc/postfix/virtual_mailboxes"), postfix_line
        )
        await asyncio.to_thread(_run_postmap, "/etc/postfix/virtual_mailboxes")
    except Exception:
        logger.debug("Postfix virtual_mailboxes update skipped (catch-all is active).")

    logger.debug("System mailbox provisioned: %s -> %s", address, maildir)


def _create_maildir(base: Path) -> None:
    """Create standard Maildir sub-directories with vmail ownership (uid/gid 5000)."""
    for subdir in ("cur", "new", "tmp"):
        (base / subdir).mkdir(parents=True, exist_ok=True)
    # Set ownership to vmail:vmail (uid 5000, gid 5000) so Dovecot can write
    import os

    for dirpath, _dirnames, _filenames in os.walk(str(base)):
        os.chown(dirpath, 5000, 5000)
    # Also ensure parent directories up to the domain level are owned by vmail
    if base.parent.exists():
        os.chown(str(base.parent), 5000, 5000)


def _dovecot_hash_password(password: str) -> str:
    """Hash a password using ``doveadm pw`` if available, else Argon2 via argon2-cffi."""
    try:
        result = subprocess.run(
            ["doveadm", "pw", "-s", "SHA512-CRYPT", "-p", password],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        # Fallback: use Argon2 hash (Dovecot 2.4+ supports it natively)
        from app.auth.service import hash_password

        return f"{{ARGON2ID}}{hash_password(password)}"


def _append_to_file(path: Path, line: str) -> None:
    """Append a single line to a file, creating it if necessary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _run_postmap(map_file: str) -> None:
    """Run ``postmap`` to rebuild a Postfix hash map after modification."""
    try:
        subprocess.run(
            ["postmap", map_file],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        logger.warning("postmap failed for %s: %s", map_file, exc)


async def _remove_from_dovecot_users(address: str) -> None:
    """Remove a user line from the Dovecot passwd-file."""
    users_path = Path(settings.dovecot_users_file)

    def _remove() -> None:
        if not users_path.exists():
            return
        lines = users_path.read_text(encoding="utf-8").splitlines(keepends=True)
        filtered = [ln for ln in lines if not ln.startswith(f"{address}:")]
        users_path.write_text("".join(filtered), encoding="utf-8")

    await asyncio.to_thread(_remove)


def _remove_directory_tree(path: Path) -> None:
    """Recursively remove a directory tree."""
    if path.exists():
        shutil.rmtree(path)


async def _imap_get_folder_stats(address: str) -> list[FolderInfo]:
    """Query IMAP STATUS for every folder in a mailbox.

    Uses the Dovecot master user to authenticate as the target mailbox.
    """
    import aioimaplib

    master_login = f"{address}*{settings.imap_master_user}"
    imap = aioimaplib.IMAP4(host=settings.imap_host, port=settings.imap_port)
    await imap.wait_hello_from_server()

    try:
        await imap.login(master_login, settings.imap_master_password)

        # List all folders
        _status_resp, folder_data = await imap.list('""', "*")
        folders: list[FolderInfo] = []

        if folder_data:
            for raw_line in folder_data:
                if isinstance(raw_line, bytes):
                    decoded = raw_line.decode("utf-8", errors="replace")
                else:
                    decoded = str(raw_line)
                # Parse folder name from LIST response
                # Format: (\flags) "delimiter" "folder_name"
                parts = decoded.rsplit('"', 2)
                if len(parts) >= 2:
                    folder_name = parts[-2].strip('" ')
                else:
                    folder_name = decoded.split()[-1].strip('"')

                if not folder_name:
                    continue

                try:
                    _st_resp, st_data = await imap.status(folder_name, "(MESSAGES UNSEEN)")
                    messages = 0
                    unseen = 0
                    if st_data:
                        line = st_data[0] if isinstance(st_data[0], str) else st_data[0].decode()
                        # Parse "INBOX (MESSAGES 42 UNSEEN 3)"
                        m_match = re.search(r"MESSAGES\s+(\d+)", line)
                        u_match = re.search(r"UNSEEN\s+(\d+)", line)
                        if m_match:
                            messages = int(m_match.group(1))
                        if u_match:
                            unseen = int(u_match.group(1))

                    folders.append(
                        FolderInfo(
                            name=folder_name,
                            message_count=messages,
                            unseen_count=unseen,
                        )
                    )
                except Exception:
                    logger.debug("Could not get STATUS for folder '%s'", folder_name)

        if not folders:
            folders.append(FolderInfo(name="INBOX", message_count=0, unseen_count=0))

        return folders
    finally:
        with contextlib.suppress(Exception):
            await imap.logout()
