"""BYO seed inbox placement classification using operator-controlled IMAP accounts."""

from __future__ import annotations

import asyncio
import contextlib
import imaplib
import re
import socket
import ssl
from dataclasses import dataclass
from typing import cast

from app.deliverability.links import _public_addresses
from app.warmup.models import WarmupAccount
from app.warmup.service import decrypt_password

_SAFE_MESSAGE_ID_RE = re.compile(r"<[^<>\s\"\\]{1,900}@[^<>\s\"\\]{1,200}>")


@dataclass(frozen=True)
class PlacementResult:
    account_id: str
    email: str
    provider: str
    placement: str
    folder: str | None
    detail: str


class _PinnedIMAP4SSL(imaplib.IMAP4_SSL):
    def __init__(
        self, host: str, address: str, port: int, context: ssl.SSLContext, timeout: float
    ) -> None:
        self._pinned_address = address
        super().__init__(host=host, port=port, ssl_context=context, timeout=timeout)

    def _create_socket(self, timeout: float) -> socket.socket:
        raw = socket.create_connection((self._pinned_address, self.port), timeout)
        return cast("socket.socket", self.ssl_context.wrap_socket(raw, server_hostname=self.host))


def _classify_sync(
    account: WarmupAccount,
    password: str,
    address: str,
    message_id: str,
    folders: list[str],
) -> PlacementResult:
    if _SAFE_MESSAGE_ID_RE.fullmatch(message_id) is None:
        return PlacementResult(
            account_id=account.id,
            email=account.email,
            provider=account.provider,
            placement="unavailable",
            folder=None,
            detail="The message does not have a safely searchable Message-ID.",
        )
    context = ssl.create_default_context()
    imap = _PinnedIMAP4SSL(
        account.imap_host,
        address,
        account.imap_port,
        context,
        12,
    )
    try:
        imap.login(account.username, password)
        for folder in folders:
            safe_folder = folder.replace("\\", "").replace('"', "")
            status, _ = imap.select(f'"{safe_folder}"', readonly=True)
            if status != "OK":
                continue
            search_status, data = imap.search(None, "HEADER", "Message-ID", f'"{message_id}"')
            if search_status == "OK" and data and data[0]:
                lowered = folder.lower()
                placement = (
                    "spam"
                    if any(token in lowered for token in ("spam", "junk"))
                    else "category"
                    if any(token in lowered for token in ("promotion", "update", "social"))
                    else "inbox"
                )
                return PlacementResult(
                    account_id=account.id,
                    email=account.email,
                    provider=account.provider,
                    placement=placement,
                    folder=folder,
                    detail=f"Matched Message-ID in {folder}.",
                )
        return PlacementResult(
            account_id=account.id,
            email=account.email,
            provider=account.provider,
            placement="missing",
            folder=None,
            detail="The Message-ID was not found in the configured folders.",
        )
    finally:
        with contextlib.suppress(Exception):
            imap.logout()


async def classify_seed_account(
    account: WarmupAccount, *, message_id: str, folders: list[str]
) -> PlacementResult:
    if account.imap_security != "ssl":
        return PlacementResult(
            account_id=account.id,
            email=account.email,
            provider=account.provider,
            placement="unavailable",
            folder=None,
            detail="Placement checks require an SSL IMAP account.",
        )
    addresses = await _public_addresses(account.imap_host, account.imap_port)
    if not addresses:
        return PlacementResult(
            account_id=account.id,
            email=account.email,
            provider=account.provider,
            placement="unavailable",
            folder=None,
            detail="The IMAP host does not resolve exclusively to public addresses.",
        )
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _classify_sync,
                account,
                decrypt_password(account.password_encrypted),
                addresses[0],
                message_id,
                folders,
            ),
            timeout=15,
        )
    except (OSError, imaplib.IMAP4.error, TimeoutError, ssl.SSLError):
        return PlacementResult(
            account_id=account.id,
            email=account.email,
            provider=account.provider,
            placement="unavailable",
            folder=None,
            detail="The seed inbox could not be queried within the bounded check budget.",
        )
