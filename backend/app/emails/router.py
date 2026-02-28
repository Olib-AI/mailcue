"""Email CRUD router -- list, get, raw, attachments, send, inject, delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.database import get_db
from app.dependencies import get_current_user
from app.emails.schemas import (
    BulkInjectRequest,
    BulkInjectResponse,
    EmailDetail,
    EmailListResponse,
    InjectEmailRequest,
    SendEmailRequest,
)
from app.emails.service import (
    bulk_inject,
    delete_email,
    get_attachment,
    get_email,
    get_email_raw,
    inject_email,
    list_emails,
    send_email,
)

router = APIRouter(prefix="/emails", tags=["Emails"])


@router.get("", response_model=EmailListResponse)
async def list_all_emails(
    mailbox: str = Query(..., description="Target mailbox address (user@domain)"),
    folder: str = Query("INBOX", description="IMAP folder name"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    search: str | None = Query(None, description="Full-text search query"),
    sort: str = Query("date_desc", description="Sort order (date_asc, date_desc)"),
    _current_user: User = Depends(get_current_user),
) -> EmailListResponse:
    """List emails in a mailbox with pagination, search, and sorting.

    Emails are fetched directly from IMAP. The ``search`` parameter
    maps to IMAP ``TEXT`` search which covers subject and body.
    """
    return await list_emails(
        mailbox=mailbox,
        folder=folder,
        page=page,
        per_page=page_size,
        search=search,
        sort=sort,
    )


@router.get("/{uid}", response_model=EmailDetail)
async def get_single_email(
    uid: str,
    mailbox: str = Query(..., description="Target mailbox address"),
    folder: str = Query("INBOX"),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EmailDetail:
    """Fetch a single email by its IMAP UID with full body and headers."""
    return await get_email(mailbox=mailbox, uid=uid, folder=folder, db=db)


@router.get("/{uid}/raw")
async def get_raw_email(
    uid: str,
    mailbox: str = Query(..., description="Target mailbox address"),
    folder: str = Query("INBOX"),
    _current_user: User = Depends(get_current_user),
) -> Response:
    """Download the raw RFC 5322 source of an email as a ``.eml`` file."""
    raw = await get_email_raw(mailbox=mailbox, uid=uid, folder=folder)
    return Response(
        content=raw,
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{uid}.eml"'},
    )


@router.get("/{uid}/attachments/{part_id}")
async def download_attachment(
    uid: str,
    part_id: str,
    mailbox: str = Query(..., description="Target mailbox address"),
    folder: str = Query("INBOX"),
    _current_user: User = Depends(get_current_user),
) -> Response:
    """Download a specific MIME attachment identified by its part ID."""
    data, content_type, filename = await get_attachment(
        mailbox=mailbox, uid=uid, part_id=part_id, folder=folder
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/send", status_code=status.HTTP_202_ACCEPTED)
async def send_new_email(
    body: SendEmailRequest,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Send an email via the local SMTP server (Postfix).

    Returns HTTP 202 (Accepted) because SMTP delivery is asynchronous --
    the message has been accepted for delivery but not yet delivered.
    """
    message_id = await send_email(body, db=db, sign=body.sign, encrypt=body.encrypt)
    return {"message": "Email accepted for delivery", "message_id": message_id}


@router.post("/inject", status_code=status.HTTP_201_CREATED)
async def inject_single_email(
    body: InjectEmailRequest,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Inject an email directly into a mailbox via IMAP APPEND.

    Bypasses SMTP delivery entirely -- the email appears in the target
    mailbox immediately. Ideal for test data setup.
    """
    uid = await inject_email(body, db=db, sign=body.sign, encrypt=body.encrypt)
    return {"uid": uid, "mailbox": body.mailbox}


@router.post(
    "/bulk-inject",
    response_model=BulkInjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_inject_emails(
    body: BulkInjectRequest,
    _current_user: User = Depends(get_current_user),
) -> BulkInjectResponse:
    """Inject multiple emails into mailboxes in a single request.

    Each email in the ``emails`` array is injected independently.
    Partial failures are reported in the response without aborting
    the entire batch.
    """
    return await bulk_inject(body)


@router.delete("/{uid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_single_email(
    uid: str,
    mailbox: str = Query(..., description="Target mailbox address"),
    folder: str = Query("INBOX"),
    _current_user: User = Depends(get_current_user),
) -> None:
    """Delete an email by UID (sets \\Deleted flag and expunges)."""
    await delete_email(mailbox=mailbox, uid=uid, folder=folder)
