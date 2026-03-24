"""Mailbox management router -- create, list, delete, stats, nested emails."""

from __future__ import annotations

import logging
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.emails.schemas import (
    BulkDeleteRequest,
    BulkDeleteResponse,
    EmailDetail,
    EmailListResponse,
    SpamActionRequest,
    UpdateFlagsRequest,
)
from app.emails.service import (
    bulk_delete_emails,
    delete_email,
    get_email,
    list_emails,
    move_email_to_folder,
    purge_mailbox,
    set_email_flags,
    train_spam,
)
from app.exceptions import AuthorizationError
from app.mailboxes.schemas import (
    DisplayNameUpdateRequest,
    MailboxCreateRequest,
    MailboxListResponse,
    MailboxResponse,
    MailboxStats,
    SignatureUpdateRequest,
)
from app.mailboxes.service import (
    _imap_get_folder_stats,
    create_mailbox,
    delete_mailbox,
    get_mailbox_by_address,
    get_mailbox_stats,
    list_mailboxes,
)

logger = logging.getLogger("mailcue.mailboxes")

router = APIRouter(prefix="/mailboxes", tags=["Mailboxes"])


def verify_mailbox_access(mailbox_address: str, current_user: User) -> None:
    """Verify the user has access to this mailbox. Admins can access any mailbox.

    Compares the decoded mailbox address against the user's canonical address
    (``username@MAILCUE_DOMAIN``).  Raises ``AuthorizationError`` on mismatch.
    """
    if current_user.is_admin:
        return
    address_lower = unquote(mailbox_address).lower()
    user_address = f"{current_user.username}@{settings.domain}".lower()
    if address_lower != user_address:
        raise AuthorizationError("You do not have access to this mailbox")


@router.get("", response_model=MailboxListResponse)
async def list_all_mailboxes(
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MailboxListResponse:
    """List all active mailboxes with email/unread counts."""
    mailboxes = await list_mailboxes(db)
    responses: list[MailboxResponse] = []
    for m in mailboxes:
        local_part = m.address.split("@", maxsplit=1)[0] if "@" in m.address else m.address
        mb_resp = MailboxResponse(
            id=m.id,
            address=m.address,
            username=local_part,
            display_name=m.display_name,
            domain=m.domain,
            is_active=m.is_active,
            created_at=m.created_at,
            quota_mb=m.quota_mb,
            signature=m.signature,
        )
        try:
            folders = await _imap_get_folder_stats(m.address)
            mb_resp.email_count = sum(f.message_count for f in folders)
            # Only count INBOX unseen for the unread badge — Junk/Trash don't count
            inbox_folders = [f for f in folders if f.name == "INBOX"]
            mb_resp.unread_count = inbox_folders[0].unseen_count if inbox_folders else 0
        except Exception:
            logger.warning("Failed to fetch IMAP stats for %s", m.address, exc_info=True)
        responses.append(mb_resp)
    return MailboxListResponse(mailboxes=responses, total=len(responses))


@router.post(
    "",
    response_model=MailboxResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_mailbox(
    body: MailboxCreateRequest,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> MailboxResponse:
    """Create a new mailbox and provision it on the mail server.

    **Admin only.** This creates a Dovecot virtual user entry and
    the corresponding Maildir directory structure.
    """
    mailbox = await create_mailbox(body, db)
    local_part = (
        mailbox.address.split("@", maxsplit=1)[0] if "@" in mailbox.address else mailbox.address
    )
    return MailboxResponse(
        id=mailbox.id,
        address=mailbox.address,
        username=local_part,
        display_name=mailbox.display_name,
        domain=mailbox.domain,
        is_active=mailbox.is_active,
        created_at=mailbox.created_at,
        quota_mb=mailbox.quota_mb,
        signature=mailbox.signature,
    )


@router.delete(
    "/{address}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_existing_mailbox(
    address: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete (deactivate) a mailbox by address and remove it from Dovecot.

    **Admin only.** The Maildir data is preserved by default.
    The ``address`` path parameter is URL-decoded automatically.
    """
    decoded_address = unquote(address)
    mailbox = await get_mailbox_by_address(decoded_address, db)
    await delete_mailbox(mailbox.id, db)


@router.get("/{mailbox_id}/stats", response_model=MailboxStats)
async def mailbox_stats(
    mailbox_id: str,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MailboxStats:
    """Retrieve email counts and folder statistics via IMAP STATUS.

    Falls back to zeroed stats when the mail server is unreachable
    (common in local development without Docker).
    """
    return await get_mailbox_stats(mailbox_id, db)


@router.post("/{address}/purge")
async def purge_mailbox_emails(
    address: str,
    _admin: User = Depends(require_admin),
) -> dict[str, int]:
    """Delete all emails from a mailbox across all folders.

    **Admin only.** The mailbox itself is preserved.
    """
    decoded = unquote(address)
    deleted = await purge_mailbox(decoded)
    return {"deleted": deleted}


# ── Nested email routes (under /mailboxes/{mailbox_address}/emails) ──────


@router.get("/{mailbox_address}/emails", response_model=EmailListResponse)
async def list_mailbox_emails(
    mailbox_address: str,
    folder: str = Query("INBOX"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = Query(None),
    sort: str = Query("date_desc"),
    _user: User = Depends(get_current_user),
) -> EmailListResponse:
    """List emails for a specific mailbox (path-based variant)."""
    verify_mailbox_access(mailbox_address, _user)
    decoded = unquote(mailbox_address)
    return await list_emails(
        mailbox=decoded,
        folder=folder,
        page=page,
        per_page=page_size,
        search=search,
        sort=sort,
    )


@router.get("/{mailbox_address}/emails/{uid}", response_model=EmailDetail)
async def get_mailbox_email(
    mailbox_address: str,
    uid: str,
    folder: str = Query("INBOX"),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EmailDetail:
    """Fetch a single email by UID from a specific mailbox."""
    verify_mailbox_access(mailbox_address, _user)
    decoded = unquote(mailbox_address)
    return await get_email(mailbox=decoded, uid=uid, folder=folder, db=db)


@router.post(
    "/{mailbox_address}/emails/bulk-delete",
    response_model=BulkDeleteResponse,
)
async def bulk_delete_mailbox_emails(
    mailbox_address: str,
    body: BulkDeleteRequest,
    folder: str = Query("INBOX"),
    _user: User = Depends(get_current_user),
) -> BulkDeleteResponse:
    """Delete multiple emails by UID from a specific mailbox."""
    verify_mailbox_access(mailbox_address, _user)
    decoded = unquote(mailbox_address)
    return await bulk_delete_emails(mailbox=decoded, request=body, folder=folder)


@router.delete(
    "/{mailbox_address}/emails/{uid}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_mailbox_email(
    mailbox_address: str,
    uid: str,
    folder: str = Query("INBOX"),
    _user: User = Depends(get_current_user),
) -> None:
    """Delete an email by UID from a specific mailbox."""
    verify_mailbox_access(mailbox_address, _user)
    decoded = unquote(mailbox_address)
    await delete_email(mailbox=decoded, uid=uid, folder=folder)


@router.patch("/{mailbox_address}/emails/{uid}/flags")
async def update_email_flags(
    mailbox_address: str,
    uid: str,
    body: UpdateFlagsRequest,
    folder: str = Query("INBOX"),
    _user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Toggle read/unread status on an email by setting or clearing the \\Seen flag."""
    verify_mailbox_access(mailbox_address, _user)
    decoded = unquote(mailbox_address)
    await set_email_flags(mailbox=decoded, uid=uid, seen=body.seen, folder=folder)
    return {"message": "Flags updated"}


# ── Spam management ───────────────────────────────────────────────


@router.post("/{mailbox_address}/emails/{uid}/spam")
async def mark_email_as_spam(
    mailbox_address: str,
    uid: str,
    body: SpamActionRequest,
    _user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Mark an email as spam by moving it from the source folder to Junk."""
    verify_mailbox_access(mailbox_address, _user)
    decoded = unquote(mailbox_address)
    await move_email_to_folder(
        mailbox=decoded,
        uid=uid,
        source_folder=body.folder,
        target_folder="Junk",
    )
    await train_spam(mailbox=decoded, uid=uid, folder=body.folder, is_spam=True)
    return {"message": "Email marked as spam"}


@router.post("/{mailbox_address}/emails/{uid}/not-spam")
async def mark_email_as_not_spam(
    mailbox_address: str,
    uid: str,
    _user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Mark an email as not spam by moving it from Junk back to INBOX."""
    verify_mailbox_access(mailbox_address, _user)
    decoded = unquote(mailbox_address)
    await move_email_to_folder(
        mailbox=decoded,
        uid=uid,
        source_folder="Junk",
        target_folder="INBOX",
    )
    await train_spam(mailbox=decoded, uid=uid, folder="Junk", is_spam=False)
    return {"message": "Email marked as not spam"}


# ── Display name management ──────────────────────────────────────


@router.put("/{address}/display-name")
async def update_mailbox_display_name(
    address: str,
    body: DisplayNameUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Set or update the display name for a mailbox.

    The user must own the mailbox (or be an admin).
    """
    verify_mailbox_access(address, current_user)
    decoded_address = unquote(address)
    mailbox = await get_mailbox_by_address(decoded_address, db)
    mailbox.display_name = body.display_name
    await db.commit()
    logger.info("Display name updated for mailbox '%s'.", decoded_address)
    return {"message": "Display name updated"}


# ── Signature management ─────────────────────────────────────────


@router.put("/{address}/signature")
async def update_mailbox_signature(
    address: str,
    body: SignatureUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Set or update the email signature for a mailbox.

    The user must own the mailbox (or be an admin).
    """
    verify_mailbox_access(address, current_user)
    decoded_address = unquote(address)
    mailbox = await get_mailbox_by_address(decoded_address, db)
    mailbox.signature = body.signature
    await db.commit()
    logger.info("Signature updated for mailbox '%s'.", decoded_address)
    return {"message": "Signature updated"}
