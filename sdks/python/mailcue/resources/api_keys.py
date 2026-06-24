"""``api_keys`` resource — issue and revoke MailCue API keys."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mailcue.resources._base import AsyncResource, SyncResource
from mailcue.types import ApiKey, CreatedApiKey


def _parse_list(payload: object) -> List[ApiKey]:
    if isinstance(payload, list):
        return [ApiKey.model_validate(item) for item in payload]
    raise ValueError("Expected list response from /auth/api-keys")


class ApiKeys(SyncResource):
    """Synchronous ``api_keys`` resource."""

    def list(self) -> List[ApiKey]:
        """List the caller's API keys.

        Example:
            >>> client.api_keys.list()
        """
        response = self._transport.request("GET", "/auth/api-keys")
        return _parse_list(response.json())

    def create(
        self,
        name: str,
        scopes: Optional[List[str]] = None,
        allowed_mailboxes: Optional[List[str]] = None,
    ) -> CreatedApiKey:
        """Create a new API key. The raw ``key`` is only returned once.

        ``scopes`` restricts the key's permissions; omit (or pass an empty
        list) for full access. ``allowed_mailboxes`` limits the key to the
        listed mailboxes; omit for all of the owner's mailboxes.

        Example:
            >>> created = client.api_keys.create(
            ...     "ci-bot",
            ...     scopes=["email:read"],
            ...     allowed_mailboxes=["bot@example.com"],
            ... )
            >>> created.key
        """
        body: Dict[str, Any] = {"name": name}
        if scopes is not None:
            body["scopes"] = scopes
        if allowed_mailboxes is not None:
            body["allowed_mailboxes"] = allowed_mailboxes
        response = self._transport.request("POST", "/auth/api-keys", json=body)
        return CreatedApiKey.model_validate(response.json())

    def update(
        self,
        key_id: str,
        name: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        allowed_mailboxes: Optional[List[str]] = None,
    ) -> ApiKey:
        """Update an API key's metadata without regenerating its secret.

        Only the fields you pass are changed. The raw ``key`` is never
        returned again.

        Example:
            >>> client.api_keys.update("01HXY...", scopes=["email:read"])
        """
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if scopes is not None:
            body["scopes"] = scopes
        if allowed_mailboxes is not None:
            body["allowed_mailboxes"] = allowed_mailboxes
        response = self._transport.request(
            "PATCH", f"/auth/api-keys/{key_id}", json=body
        )
        return ApiKey.model_validate(response.json())

    def delete(self, key_id: str) -> None:
        """Revoke an API key by ID.

        Example:
            >>> client.api_keys.delete("01HXY...")
        """
        self._transport.request("DELETE", f"/auth/api-keys/{key_id}")


class AsyncApiKeys(AsyncResource):
    """Asynchronous ``api_keys`` resource."""

    async def list(self) -> List[ApiKey]:
        """Async variant of :meth:`ApiKeys.list`."""
        response = await self._transport.request("GET", "/auth/api-keys")
        return _parse_list(response.json())

    async def create(
        self,
        name: str,
        scopes: Optional[List[str]] = None,
        allowed_mailboxes: Optional[List[str]] = None,
    ) -> CreatedApiKey:
        """Async variant of :meth:`ApiKeys.create`."""
        body: Dict[str, Any] = {"name": name}
        if scopes is not None:
            body["scopes"] = scopes
        if allowed_mailboxes is not None:
            body["allowed_mailboxes"] = allowed_mailboxes
        response = await self._transport.request("POST", "/auth/api-keys", json=body)
        return CreatedApiKey.model_validate(response.json())

    async def update(
        self,
        key_id: str,
        name: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        allowed_mailboxes: Optional[List[str]] = None,
    ) -> ApiKey:
        """Async variant of :meth:`ApiKeys.update`."""
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if scopes is not None:
            body["scopes"] = scopes
        if allowed_mailboxes is not None:
            body["allowed_mailboxes"] = allowed_mailboxes
        response = await self._transport.request(
            "PATCH", f"/auth/api-keys/{key_id}", json=body
        )
        return ApiKey.model_validate(response.json())

    async def delete(self, key_id: str) -> None:
        """Async variant of :meth:`ApiKeys.delete`."""
        await self._transport.request("DELETE", f"/auth/api-keys/{key_id}")
