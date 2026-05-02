"""Top-level :class:`Mailcue` and :class:`AsyncMailcue` clients."""

from __future__ import annotations

from typing import Optional

import httpx

from mailcue.auth import ApiKeyAuth, AuthStrategy, BearerAuth, NoAuth
from mailcue.events import AsyncSSEClient, SSEClient
from mailcue.resources.aliases import Aliases, AsyncAliases
from mailcue.resources.api_keys import ApiKeys, AsyncApiKeys
from mailcue.resources.domains import AsyncDomains, Domains
from mailcue.resources.emails import AsyncEmails, Emails
from mailcue.resources.gpg import AsyncGpg, Gpg
from mailcue.resources.mailboxes import AsyncMailboxes, Mailboxes
from mailcue.resources.system import AsyncSystem, System
from mailcue.transport import (
    DEFAULT_BASE_URL,
    AsyncTransport,
    SyncTransport,
    build_config,
)


def _resolve_auth(
    api_key: Optional[str],
    bearer_token: Optional[str],
) -> AuthStrategy:
    if api_key and bearer_token:
        raise ValueError("Pass either api_key or bearer_token, not both")
    if api_key:
        return ApiKeyAuth(api_key)
    if bearer_token:
        return BearerAuth(bearer_token)
    return NoAuth()


class Mailcue:
    """Synchronous MailCue API client.

    Example:
        >>> from mailcue import Mailcue
        >>> client = Mailcue(api_key="mc_...", base_url="https://mail.example.com")
        >>> client.emails.send(
        ...     from_="hello@example.com",
        ...     to=["user@example.com"],
        ...     subject="Hi",
        ...     html="<h1>Hello</h1>",
        ... )
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        bearer_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_cap: float = 8.0,
        verify: bool = True,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        auth = _resolve_auth(api_key, bearer_token)
        config = build_config(
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            backoff_base=backoff_base,
            backoff_cap=backoff_cap,
            verify=verify,
        )
        self._transport = SyncTransport(config, auth, client=http_client)
        self.emails = Emails(self._transport)
        self.mailboxes = Mailboxes(self._transport)
        self.domains = Domains(self._transport)
        self.aliases = Aliases(self._transport)
        self.gpg = Gpg(self._transport)
        self.api_keys = ApiKeys(self._transport)
        self.system = System(self._transport)
        self.events = SSEClient(self._transport)

    @property
    def base_url(self) -> str:
        return self._transport.base_url

    def close(self) -> None:
        """Close the underlying HTTP client (only if owned by this client)."""
        self._transport.close()

    def __enter__(self) -> "Mailcue":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class AsyncMailcue:
    """Asynchronous MailCue API client.

    Example:
        >>> import asyncio
        >>> from mailcue import AsyncMailcue
        >>> async def main() -> None:
        ...     async with AsyncMailcue(api_key="mc_...") as client:
        ...         await client.emails.send(
        ...             from_="hello@example.com",
        ...             to=["user@example.com"],
        ...             subject="Hi",
        ...             html="<h1>Hello</h1>",
        ...         )
        >>> asyncio.run(main())
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        bearer_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_cap: float = 8.0,
        verify: bool = True,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        auth = _resolve_auth(api_key, bearer_token)
        config = build_config(
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            backoff_base=backoff_base,
            backoff_cap=backoff_cap,
            verify=verify,
        )
        self._transport = AsyncTransport(config, auth, client=http_client)
        self.emails = AsyncEmails(self._transport)
        self.mailboxes = AsyncMailboxes(self._transport)
        self.domains = AsyncDomains(self._transport)
        self.aliases = AsyncAliases(self._transport)
        self.gpg = AsyncGpg(self._transport)
        self.api_keys = AsyncApiKeys(self._transport)
        self.system = AsyncSystem(self._transport)
        self.events = AsyncSSEClient(self._transport)

    @property
    def base_url(self) -> str:
        return self._transport.base_url

    async def aclose(self) -> None:
        """Close the underlying HTTP client (only if owned by this client)."""
        await self._transport.aclose()

    async def __aenter__(self) -> "AsyncMailcue":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


__all__ = ["DEFAULT_BASE_URL", "AsyncMailcue", "Mailcue"]
