"""``mailboxes`` resource."""

from __future__ import annotations

from typing import Any, Dict, Optional

from mailcue.resources._base import AsyncResource, SyncResource
from mailcue.types import (
    EmailListResponse,
    Mailbox,
    MailboxListResponse,
    MailboxStats,
)


def _create_payload(
    username: str,
    password: str,
    *,
    domain: Optional[str],
    display_name: str,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "username": username,
        "password": password,
        "display_name": display_name,
    }
    if domain is not None:
        payload["domain"] = domain
    return payload


def _list_emails_params(
    folder: str,
    page: int,
    page_size: int,
    search: Optional[str],
    sort: str,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "folder": folder,
        "page": page,
        "page_size": page_size,
        "sort": sort,
    }
    if search is not None:
        params["search"] = search
    return params


class Mailboxes(SyncResource):
    """Synchronous ``mailboxes`` resource."""

    def list(self) -> MailboxListResponse:
        """List all mailboxes.

        Example:
            >>> client.mailboxes.list()
        """
        response = self._transport.request("GET", "/mailboxes")
        return MailboxListResponse.model_validate(response.json())

    def create(
        self,
        username: str,
        password: str,
        *,
        domain: Optional[str] = None,
        display_name: str = "",
    ) -> Mailbox:
        """Create a new mailbox.

        Example:
            >>> client.mailboxes.create("alice", "s3cret", domain="example.com")
        """
        payload = _create_payload(username, password, domain=domain, display_name=display_name)
        response = self._transport.request("POST", "/mailboxes", json=payload)
        return Mailbox.model_validate(response.json())

    def delete(self, address: str) -> None:
        """Delete a mailbox by address.

        Example:
            >>> client.mailboxes.delete("alice@example.com")
        """
        self._transport.request("DELETE", f"/mailboxes/{address}")

    def stats(self, mailbox_id: str) -> MailboxStats:
        """Return IMAP STATUS counts for a mailbox.

        Example:
            >>> client.mailboxes.stats(mailbox_id="abc")
        """
        response = self._transport.request("GET", f"/mailboxes/{mailbox_id}/stats")
        return MailboxStats.model_validate(response.json())

    def purge(self, address: str) -> Dict[str, Any]:
        """Permanently delete every email in a mailbox.

        Example:
            >>> client.mailboxes.purge("alice@example.com")
        """
        response = self._transport.request("POST", f"/mailboxes/{address}/purge")
        result: Dict[str, Any] = response.json() if response.content else {}
        return result

    def list_emails(
        self,
        address: str,
        *,
        folder: str = "INBOX",
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
        sort: str = "date_desc",
    ) -> EmailListResponse:
        """List emails in a mailbox (mailbox-scoped variant of ``emails.list``).

        Example:
            >>> client.mailboxes.list_emails("alice@example.com")
        """
        params = _list_emails_params(folder, page, page_size, search, sort)
        response = self._transport.request("GET", f"/mailboxes/{address}/emails", params=params)
        return EmailListResponse.model_validate(response.json())


class AsyncMailboxes(AsyncResource):
    """Asynchronous ``mailboxes`` resource."""

    async def list(self) -> MailboxListResponse:
        """Async variant of :meth:`Mailboxes.list`."""
        response = await self._transport.request("GET", "/mailboxes")
        return MailboxListResponse.model_validate(response.json())

    async def create(
        self,
        username: str,
        password: str,
        *,
        domain: Optional[str] = None,
        display_name: str = "",
    ) -> Mailbox:
        """Async variant of :meth:`Mailboxes.create`."""
        payload = _create_payload(username, password, domain=domain, display_name=display_name)
        response = await self._transport.request("POST", "/mailboxes", json=payload)
        return Mailbox.model_validate(response.json())

    async def delete(self, address: str) -> None:
        """Async variant of :meth:`Mailboxes.delete`."""
        await self._transport.request("DELETE", f"/mailboxes/{address}")

    async def stats(self, mailbox_id: str) -> MailboxStats:
        """Async variant of :meth:`Mailboxes.stats`."""
        response = await self._transport.request("GET", f"/mailboxes/{mailbox_id}/stats")
        return MailboxStats.model_validate(response.json())

    async def purge(self, address: str) -> Dict[str, Any]:
        """Async variant of :meth:`Mailboxes.purge`."""
        response = await self._transport.request("POST", f"/mailboxes/{address}/purge")
        result: Dict[str, Any] = response.json() if response.content else {}
        return result

    async def list_emails(
        self,
        address: str,
        *,
        folder: str = "INBOX",
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
        sort: str = "date_desc",
    ) -> EmailListResponse:
        """Async variant of :meth:`Mailboxes.list_emails`."""
        params = _list_emails_params(folder, page, page_size, search, sort)
        response = await self._transport.request(
            "GET", f"/mailboxes/{address}/emails", params=params
        )
        return EmailListResponse.model_validate(response.json())
