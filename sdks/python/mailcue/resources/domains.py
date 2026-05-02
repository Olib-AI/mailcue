"""``domains`` resource."""

from __future__ import annotations

from mailcue.resources._base import AsyncResource, SyncResource
from mailcue.types import (
    DnsCheckResponse,
    Domain,
    DomainDetail,
    DomainListResponse,
)


class Domains(SyncResource):
    """Synchronous ``domains`` resource."""

    def list(self) -> DomainListResponse:
        """List all managed domains.

        Example:
            >>> client.domains.list()
        """
        response = self._transport.request("GET", "/domains")
        return DomainListResponse.model_validate(response.json())

    def create(self, name: str) -> Domain:
        """Register a new domain.

        Example:
            >>> client.domains.create("example.com")
        """
        response = self._transport.request("POST", "/domains", json={"name": name})
        return Domain.model_validate(response.json())

    def get(self, name: str) -> DomainDetail:
        """Fetch a single domain with full DNS details.

        Example:
            >>> client.domains.get("example.com")
        """
        response = self._transport.request("GET", f"/domains/{name}")
        return DomainDetail.model_validate(response.json())

    def verify_dns(self, name: str) -> DnsCheckResponse:
        """Run a live DNS verification check.

        Example:
            >>> client.domains.verify_dns("example.com")
        """
        response = self._transport.request("POST", f"/domains/{name}/verify-dns")
        return DnsCheckResponse.model_validate(response.json())

    def delete(self, name: str) -> None:
        """Remove a domain.

        Example:
            >>> client.domains.delete("example.com")
        """
        self._transport.request("DELETE", f"/domains/{name}")


class AsyncDomains(AsyncResource):
    """Asynchronous ``domains`` resource."""

    async def list(self) -> DomainListResponse:
        """Async variant of :meth:`Domains.list`."""
        response = await self._transport.request("GET", "/domains")
        return DomainListResponse.model_validate(response.json())

    async def create(self, name: str) -> Domain:
        """Async variant of :meth:`Domains.create`."""
        response = await self._transport.request("POST", "/domains", json={"name": name})
        return Domain.model_validate(response.json())

    async def get(self, name: str) -> DomainDetail:
        """Async variant of :meth:`Domains.get`."""
        response = await self._transport.request("GET", f"/domains/{name}")
        return DomainDetail.model_validate(response.json())

    async def verify_dns(self, name: str) -> DnsCheckResponse:
        """Async variant of :meth:`Domains.verify_dns`."""
        response = await self._transport.request("POST", f"/domains/{name}/verify-dns")
        return DnsCheckResponse.model_validate(response.json())

    async def delete(self, name: str) -> None:
        """Async variant of :meth:`Domains.delete`."""
        await self._transport.request("DELETE", f"/domains/{name}")
