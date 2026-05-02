"""``aliases`` resource (admin-only)."""

from __future__ import annotations

from typing import Optional

from mailcue.resources._base import AsyncResource, SyncResource
from mailcue.types import Alias, AliasListResponse


class Aliases(SyncResource):
    """Synchronous ``aliases`` resource."""

    def list(self) -> AliasListResponse:
        """List all email aliases.

        Example:
            >>> client.aliases.list()
        """
        response = self._transport.request("GET", "/aliases")
        return AliasListResponse.model_validate(response.json())

    def create(self, source_address: str, destination_address: str) -> Alias:
        """Create a new alias mapping ``source`` to ``destination``.

        Example:
            >>> client.aliases.create("sales@example.com", "alice@example.com")
        """
        payload = {
            "source_address": source_address,
            "destination_address": destination_address,
        }
        response = self._transport.request("POST", "/aliases", json=payload)
        return Alias.model_validate(response.json())

    def get(self, alias_id: int) -> Alias:
        """Fetch an alias by numeric ID.

        Example:
            >>> client.aliases.get(42)
        """
        response = self._transport.request("GET", f"/aliases/{alias_id}")
        return Alias.model_validate(response.json())

    def update(
        self,
        alias_id: int,
        *,
        destination_address: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> Alias:
        """Update an alias's destination or enabled flag.

        Example:
            >>> client.aliases.update(42, enabled=False)
        """
        payload: dict[str, object] = {}
        if destination_address is not None:
            payload["destination_address"] = destination_address
        if enabled is not None:
            payload["enabled"] = enabled
        response = self._transport.request("PUT", f"/aliases/{alias_id}", json=payload)
        return Alias.model_validate(response.json())

    def delete(self, alias_id: int) -> None:
        """Delete an alias.

        Example:
            >>> client.aliases.delete(42)
        """
        self._transport.request("DELETE", f"/aliases/{alias_id}")


class AsyncAliases(AsyncResource):
    """Asynchronous ``aliases`` resource."""

    async def list(self) -> AliasListResponse:
        """Async variant of :meth:`Aliases.list`."""
        response = await self._transport.request("GET", "/aliases")
        return AliasListResponse.model_validate(response.json())

    async def create(self, source_address: str, destination_address: str) -> Alias:
        """Async variant of :meth:`Aliases.create`."""
        payload = {
            "source_address": source_address,
            "destination_address": destination_address,
        }
        response = await self._transport.request("POST", "/aliases", json=payload)
        return Alias.model_validate(response.json())

    async def get(self, alias_id: int) -> Alias:
        """Async variant of :meth:`Aliases.get`."""
        response = await self._transport.request("GET", f"/aliases/{alias_id}")
        return Alias.model_validate(response.json())

    async def update(
        self,
        alias_id: int,
        *,
        destination_address: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> Alias:
        """Async variant of :meth:`Aliases.update`."""
        payload: dict[str, object] = {}
        if destination_address is not None:
            payload["destination_address"] = destination_address
        if enabled is not None:
            payload["enabled"] = enabled
        response = await self._transport.request("PUT", f"/aliases/{alias_id}", json=payload)
        return Alias.model_validate(response.json())

    async def delete(self, alias_id: int) -> None:
        """Async variant of :meth:`Aliases.delete`."""
        await self._transport.request("DELETE", f"/aliases/{alias_id}")
