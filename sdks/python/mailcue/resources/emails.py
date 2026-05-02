"""``emails`` resource — send, list, fetch, inject, delete."""

from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from mailcue.resources._base import AsyncResource, SyncResource
from mailcue.types import (
    BulkInjectResponse,
    EmailDetail,
    EmailListResponse,
    SendResult,
)

AttachmentInput = Mapping[str, Any]
AttachmentContent = Union[bytes, str, Path]


def _encode_attachment_content(content: AttachmentContent) -> str:
    if isinstance(content, Path):
        raw = content.read_bytes()
    elif isinstance(content, str):
        raw = content.encode("utf-8")
    elif isinstance(content, (bytes, bytearray)):
        raw = bytes(content)
    else:
        raise TypeError(
            f"Attachment content must be bytes, str, or pathlib.Path; got {type(content).__name__}"
        )
    return base64.b64encode(raw).decode("ascii")


def _normalize_attachments(
    attachments: Optional[List[AttachmentInput]],
) -> List[Dict[str, str]]:
    if not attachments:
        return []
    normalized: List[Dict[str, str]] = []
    for index, attachment in enumerate(attachments):
        try:
            filename = attachment["filename"]
        except KeyError as exc:
            raise ValueError(f"Attachment #{index} missing 'filename'") from exc
        content_type = attachment.get("content_type", "application/octet-stream")
        if "data" in attachment:
            data = attachment["data"]
            if isinstance(data, bytearray):
                encoded = _encode_attachment_content(bytes(data))
            elif isinstance(data, (bytes, str, Path)):
                encoded = _encode_attachment_content(data)
            else:
                raise TypeError(f"Attachment #{index} 'data' must be bytes, str, or Path")
        elif "content" in attachment:
            encoded = _encode_attachment_content(attachment["content"])
        else:
            raise ValueError(f"Attachment #{index} requires 'content' or 'data'")
        normalized.append(
            {
                "filename": str(filename),
                "content_type": str(content_type),
                "data": encoded,
            }
        )
    return normalized


def _send_payload(
    *,
    from_: str,
    to: List[str],
    subject: str,
    html: Optional[str],
    text: Optional[str],
    cc: Optional[List[str]],
    bcc: Optional[List[str]],
    reply_to: Optional[str],
    headers: Optional[Mapping[str, str]],
    attachments: Optional[List[AttachmentInput]],
    gpg_sign: bool,
    gpg_encrypt: bool,
) -> Dict[str, Any]:
    if html is None and text is None:
        raise ValueError("send() requires at least one of 'html' or 'text'")
    if html is not None and text is not None:
        # MailCue's SendEmailRequest exposes a single body+body_type; pick HTML
        # since recipients can downgrade to plain. The server is the source of
        # truth for what's accepted, so we keep this client-side mapping
        # explicit rather than silently dropping a value.
        body = html
        body_type = "html"
    elif html is not None:
        body = html
        body_type = "html"
    else:
        body = text or ""
        body_type = "plain"

    payload: Dict[str, Any] = {
        "from_address": from_,
        "to_addresses": list(to),
        "subject": subject,
        "body": body,
        "body_type": body_type,
        "sign": gpg_sign,
        "encrypt": gpg_encrypt,
    }
    if cc:
        payload["cc_addresses"] = list(cc)
    if bcc:
        payload["bcc_addresses"] = list(bcc)
    if reply_to is not None:
        payload["reply_to"] = reply_to
    normalized_attachments = _normalize_attachments(attachments)
    if normalized_attachments:
        payload["attachments"] = normalized_attachments
    if headers:
        payload["headers"] = dict(headers)
    return payload


def _inject_payload(
    *,
    mailbox: str,
    from_address: str,
    to_addresses: List[str],
    subject: str,
    html_body: Optional[str],
    text_body: Optional[str],
    headers: Optional[Mapping[str, str]],
    realistic_headers: bool,
    date: Optional[datetime],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "mailbox": mailbox,
        "from_address": from_address,
        "to_addresses": list(to_addresses),
        "subject": subject,
        "realistic_headers": realistic_headers,
    }
    if html_body is not None:
        payload["html_body"] = html_body
    if text_body is not None:
        payload["text_body"] = text_body
    if headers:
        payload["headers"] = dict(headers)
    if date is not None:
        payload["date"] = date.isoformat()
    return payload


def _list_params(
    *,
    mailbox: str,
    folder: str,
    page: int,
    page_size: int,
    search: Optional[str],
    sort: str,
    thread_view: bool,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "mailbox": mailbox,
        "folder": folder,
        "page": page,
        "page_size": page_size,
        "sort": sort,
        "thread_view": thread_view,
    }
    if search is not None:
        params["search"] = search
    return params


class Emails(SyncResource):
    """Synchronous ``emails`` resource."""

    def send(
        self,
        *,
        from_: str,
        to: List[str],
        subject: str,
        html: Optional[str] = None,
        text: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        reply_to: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        attachments: Optional[List[AttachmentInput]] = None,
        gpg_sign: bool = False,
        gpg_encrypt: bool = False,
    ) -> SendResult:
        """Send an email through Postfix.

        Example:
            >>> client.emails.send(
            ...     from_="hello@example.com",
            ...     to=["user@example.com"],
            ...     subject="Welcome",
            ...     html="<h1>Hi</h1>",
            ... )
        """
        payload = _send_payload(
            from_=from_,
            to=to,
            subject=subject,
            html=html,
            text=text,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            headers=headers,
            attachments=attachments,
            gpg_sign=gpg_sign,
            gpg_encrypt=gpg_encrypt,
        )
        response = self._transport.request("POST", "/emails/send", json=payload)
        body = response.json() if response.content else {}
        return SendResult.model_validate(body)

    def list(
        self,
        *,
        mailbox: str,
        folder: str = "INBOX",
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
        sort: str = "date_desc",
        thread_view: bool = False,
    ) -> EmailListResponse:
        """List emails in a mailbox folder.

        Example:
            >>> client.emails.list(mailbox="user@example.com", page_size=10)
        """
        params = _list_params(
            mailbox=mailbox,
            folder=folder,
            page=page,
            page_size=page_size,
            search=search,
            sort=sort,
            thread_view=thread_view,
        )
        response = self._transport.request("GET", "/emails", params=params)
        return EmailListResponse.model_validate(response.json())

    def get(
        self,
        uid: str,
        *,
        mailbox: str,
        folder: str = "INBOX",
    ) -> EmailDetail:
        """Fetch a single email by its IMAP UID.

        Example:
            >>> client.emails.get("123", mailbox="user@example.com")
        """
        params = {"mailbox": mailbox, "folder": folder}
        response = self._transport.request("GET", f"/emails/{uid}", params=params)
        return EmailDetail.model_validate(response.json())

    def get_raw(
        self,
        uid: str,
        *,
        mailbox: str,
        folder: str = "INBOX",
    ) -> bytes:
        """Download the raw RFC-822 message bytes.

        Example:
            >>> raw = client.emails.get_raw("123", mailbox="user@example.com")
        """
        params = {"mailbox": mailbox, "folder": folder}
        response = self._transport.request(
            "GET",
            f"/emails/{uid}/raw",
            params=params,
            headers={"Accept": "*/*"},
        )
        return response.content

    def get_attachment(
        self,
        uid: str,
        part_id: str,
        *,
        mailbox: str,
        folder: str = "INBOX",
    ) -> bytes:
        """Download a single MIME attachment by ``part_id``.

        Example:
            >>> client.emails.get_attachment("123", "2", mailbox="user@example.com")
        """
        params = {"mailbox": mailbox, "folder": folder}
        response = self._transport.request(
            "GET",
            f"/emails/{uid}/attachments/{part_id}",
            params=params,
            headers={"Accept": "*/*"},
        )
        return response.content

    def delete(
        self,
        uid: str,
        *,
        mailbox: str,
        folder: str = "INBOX",
    ) -> None:
        """Permanently delete an email.

        Example:
            >>> client.emails.delete("123", mailbox="user@example.com")
        """
        params = {"mailbox": mailbox, "folder": folder}
        self._transport.request("DELETE", f"/emails/{uid}", params=params)

    def inject(
        self,
        *,
        mailbox: str,
        from_address: str,
        to_addresses: List[str],
        subject: str,
        html_body: Optional[str] = None,
        text_body: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        realistic_headers: bool = True,
        date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Inject an email directly into a mailbox via IMAP APPEND. **Admin-only.**

        Example:
            >>> client.emails.inject(
            ...     mailbox="user@example.com",
            ...     from_address="newsletter@brand.io",
            ...     to_addresses=["user@example.com"],
            ...     subject="Welcome",
            ...     html_body="<p>hi</p>",
            ... )
        """
        payload = _inject_payload(
            mailbox=mailbox,
            from_address=from_address,
            to_addresses=to_addresses,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            headers=headers,
            realistic_headers=realistic_headers,
            date=date,
        )
        response = self._transport.request("POST", "/emails/inject", json=payload)
        result: Dict[str, Any] = response.json() if response.content else {}
        return result

    def bulk_inject(self, emails: List[Mapping[str, Any]]) -> BulkInjectResponse:
        """Inject many emails at once. **Admin-only.**

        Example:
            >>> client.emails.bulk_inject([
            ...     {"mailbox": "u@e.com", "from_address": "x@y.com",
            ...      "to_addresses": ["u@e.com"], "subject": "Hi"}
            ... ])
        """
        payload = {"emails": [dict(e) for e in emails]}
        response = self._transport.request("POST", "/emails/bulk-inject", json=payload)
        return BulkInjectResponse.model_validate(response.json())


class AsyncEmails(AsyncResource):
    """Asynchronous ``emails`` resource."""

    async def send(
        self,
        *,
        from_: str,
        to: List[str],
        subject: str,
        html: Optional[str] = None,
        text: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        reply_to: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        attachments: Optional[List[AttachmentInput]] = None,
        gpg_sign: bool = False,
        gpg_encrypt: bool = False,
    ) -> SendResult:
        """Async variant of :meth:`Emails.send`."""
        payload = _send_payload(
            from_=from_,
            to=to,
            subject=subject,
            html=html,
            text=text,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            headers=headers,
            attachments=attachments,
            gpg_sign=gpg_sign,
            gpg_encrypt=gpg_encrypt,
        )
        response = await self._transport.request("POST", "/emails/send", json=payload)
        body = response.json() if response.content else {}
        return SendResult.model_validate(body)

    async def list(
        self,
        *,
        mailbox: str,
        folder: str = "INBOX",
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
        sort: str = "date_desc",
        thread_view: bool = False,
    ) -> EmailListResponse:
        """Async variant of :meth:`Emails.list`."""
        params = _list_params(
            mailbox=mailbox,
            folder=folder,
            page=page,
            page_size=page_size,
            search=search,
            sort=sort,
            thread_view=thread_view,
        )
        response = await self._transport.request("GET", "/emails", params=params)
        return EmailListResponse.model_validate(response.json())

    async def get(
        self,
        uid: str,
        *,
        mailbox: str,
        folder: str = "INBOX",
    ) -> EmailDetail:
        """Async variant of :meth:`Emails.get`."""
        params = {"mailbox": mailbox, "folder": folder}
        response = await self._transport.request("GET", f"/emails/{uid}", params=params)
        return EmailDetail.model_validate(response.json())

    async def get_raw(
        self,
        uid: str,
        *,
        mailbox: str,
        folder: str = "INBOX",
    ) -> bytes:
        """Async variant of :meth:`Emails.get_raw`."""
        params = {"mailbox": mailbox, "folder": folder}
        response = await self._transport.request(
            "GET",
            f"/emails/{uid}/raw",
            params=params,
            headers={"Accept": "*/*"},
        )
        return response.content

    async def get_attachment(
        self,
        uid: str,
        part_id: str,
        *,
        mailbox: str,
        folder: str = "INBOX",
    ) -> bytes:
        """Async variant of :meth:`Emails.get_attachment`."""
        params = {"mailbox": mailbox, "folder": folder}
        response = await self._transport.request(
            "GET",
            f"/emails/{uid}/attachments/{part_id}",
            params=params,
            headers={"Accept": "*/*"},
        )
        return response.content

    async def delete(
        self,
        uid: str,
        *,
        mailbox: str,
        folder: str = "INBOX",
    ) -> None:
        """Async variant of :meth:`Emails.delete`."""
        params = {"mailbox": mailbox, "folder": folder}
        await self._transport.request("DELETE", f"/emails/{uid}", params=params)

    async def inject(
        self,
        *,
        mailbox: str,
        from_address: str,
        to_addresses: List[str],
        subject: str,
        html_body: Optional[str] = None,
        text_body: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
        realistic_headers: bool = True,
        date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Async variant of :meth:`Emails.inject`."""
        payload = _inject_payload(
            mailbox=mailbox,
            from_address=from_address,
            to_addresses=to_addresses,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            headers=headers,
            realistic_headers=realistic_headers,
            date=date,
        )
        response = await self._transport.request("POST", "/emails/inject", json=payload)
        result: Dict[str, Any] = response.json() if response.content else {}
        return result

    async def bulk_inject(self, emails: List[Mapping[str, Any]]) -> BulkInjectResponse:
        """Async variant of :meth:`Emails.bulk_inject`."""
        payload = {"emails": [dict(e) for e in emails]}
        response = await self._transport.request("POST", "/emails/bulk-inject", json=payload)
        return BulkInjectResponse.model_validate(response.json())
