"""``api_keys`` resource — issue and revoke MailCue API keys."""

from __future__ import annotations

from typing import List

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

    def create(self, name: str) -> CreatedApiKey:
        """Create a new API key. The raw ``key`` is only returned once.

        Example:
            >>> created = client.api_keys.create("ci-bot")
            >>> created.key
        """
        response = self._transport.request("POST", "/auth/api-keys", json={"name": name})
        return CreatedApiKey.model_validate(response.json())

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

    async def create(self, name: str) -> CreatedApiKey:
        """Async variant of :meth:`ApiKeys.create`."""
        response = await self._transport.request("POST", "/auth/api-keys", json={"name": name})
        return CreatedApiKey.model_validate(response.json())

    async def delete(self, key_id: str) -> None:
        """Async variant of :meth:`ApiKeys.delete`."""
        await self._transport.request("DELETE", f"/auth/api-keys/{key_id}")
