"""Mailbox management router -- create, list, delete, stats, nested emails."""

from __future__ import annotations

import logging
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.database import get_db
from app.dependencies import get_current_user
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
    get_mailbox,
    get_mailbox_by_address,
    get_mailbox_stats,
    list_mailboxes,
)

logger = logging.getLogger("mailcue.mailboxes")

router = APIRouter(prefix="/mailboxes", tags=["Mailboxes"])


async def verify_mailbox_access(
    mailbox_address: str, current_user: User, db: AsyncSession
) -> None:
    """Verify the user owns this mailbox.

    Every user -- including admins -- can only access their own
    mailboxes.  Raises ``AuthorizationError`` on mismatch.
    """
    decoded = unquote(mailbox_address).lower()
    mailbox = await get_mailbox_by_address(decoded, db)
    if mailbox.user_id != current_user.id:
        raise AuthorizationError("You do not have access to this mailbox")


@router.get("", response_model=MailboxListResponse)
async def list_all_mailboxes(
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MailboxListResponse:
    """List active mailboxes with email/unread counts.

    Non-admin users only see their own mailboxes.
    """
    mailboxes = await list_mailboxes(db, user=_current_user)
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
            owner_id=m.user_id,
        )
        try:
            folders = await _imap_get_folder_stats(m.address)
            mb_resp.email_count = sum(f.message_count for f in folders)
            # Only count INBOX unseen for the unread badge — Junk/Trash don't count
            inbox_folders = [f for f in folders if f.name == "INBOX"]
            mb_resp.unread_count = inbox_folders[0].unseen_count if inbox_folders else 0
            junk_folders = [f for f in folders if f.name == "Junk"]
            mb_resp.junk_count = junk_folders[0].unseen_count if junk_folders else 0
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MailboxResponse:
    """Create a new mailbox and provision it on the mail server.

    Any authenticated user can create mailboxes up to their quota.
    """
    mailbox = await create_mailbox(body, db, user_id=current_user.id)
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
        owner_id=mailbox.user_id,
    )


@router.delete(
    "/{address}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_existing_mailbox(
    address: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete (deactivate) a mailbox by address and remove it from Dovecot.

    Admins can delete any mailbox; users can delete their own.
    The Maildir data is preserved by default.
    """
    await verify_mailbox_access(address, current_user, db)
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
    mailbox = await get_mailbox(mailbox_id, db)
    if mailbox.user_id != _current_user.id:
        raise AuthorizationError("You do not have access to this mailbox")
    return await get_mailbox_stats(mailbox_id, db)


@router.post("/{address}/purge")
async def purge_mailbox_emails(
    address: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Delete all emails from a mailbox across all folders.

    Admins can purge any mailbox; users can purge their own.
    """
    await verify_mailbox_access(address, current_user, db)
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
    db: AsyncSession = Depends(get_db),
) -> EmailListResponse:
    """List emails for a specific mailbox (path-based variant)."""
    await verify_mailbox_access(mailbox_address, _user, db)
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
    await verify_mailbox_access(mailbox_address, _user, db)
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
    db: AsyncSession = Depends(get_db),
) -> BulkDeleteResponse:
    """Delete multiple emails by UID from a specific mailbox."""
    await verify_mailbox_access(mailbox_address, _user, db)
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
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an email by UID from a specific mailbox."""
    await verify_mailbox_access(mailbox_address, _user, db)
    decoded = unquote(mailbox_address)
    await delete_email(mailbox=decoded, uid=uid, folder=folder)


@router.patch("/{mailbox_address}/emails/{uid}/flags")
async def update_email_flags(
    mailbox_address: str,
    uid: str,
    body: UpdateFlagsRequest,
    folder: str = Query("INBOX"),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Toggle read/unread status on an email by setting or clearing the \\Seen flag."""
    await verify_mailbox_access(mailbox_address, _user, db)
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
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Mark an email as spam by moving it from the source folder to Junk."""
    await verify_mailbox_access(mailbox_address, _user, db)
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
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Mark an email as not spam by moving it from Junk back to INBOX."""
    await verify_mailbox_access(mailbox_address, _user, db)
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
    await verify_mailbox_access(address, current_user, db)
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
    await verify_mailbox_access(address, current_user, db)
    decoded_address = unquote(address)
    mailbox = await get_mailbox_by_address(decoded_address, db)
    mailbox.signature = body.signature
    await db.commit()
    logger.info("Signature updated for mailbox '%s'.", decoded_address)
    return {"message": "Signature updated"}
