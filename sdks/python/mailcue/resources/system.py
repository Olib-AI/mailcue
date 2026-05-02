"""``system`` resource — health, certificate metadata, and downloads."""

from __future__ import annotations

from typing import Any, Dict

from mailcue.resources._base import AsyncResource, SyncResource
from mailcue.types import HealthResponse, TlsCertificateStatus


class System(SyncResource):
    """Synchronous ``system`` resource."""

    def health(self) -> HealthResponse:
        """Hit the unauthenticated health endpoint.

        Example:
            >>> client.system.health()
        """
        response = self._transport.request("GET", "/health")
        body = response.json()
        if isinstance(body, dict):
            return HealthResponse.model_validate(body)
        return HealthResponse(status=str(body))

    def get_certificate(self) -> TlsCertificateStatus:
        """Return TLS certificate metadata.

        Example:
            >>> client.system.get_certificate().common_name
        """
        response = self._transport.request("GET", "/system/certificate")
        return TlsCertificateStatus.model_validate(response.json())

    def download_certificate(self) -> bytes:
        """Download the configured TLS certificate (PEM bytes).

        Example:
            >>> pem = client.system.download_certificate()
        """
        response = self._transport.request(
            "GET", "/system/certificate/download", headers={"Accept": "*/*"}
        )
        return response.content

    def settings(self) -> Dict[str, Any]:
        """Fetch raw server settings.

        Example:
            >>> client.system.settings()
        """
        response = self._transport.request("GET", "/system/settings")
        result: Dict[str, Any] = response.json()
        return result

    def tls_status(self) -> TlsCertificateStatus:
        """Return TLS upload status.

        Example:
            >>> client.system.tls_status()
        """
        response = self._transport.request("GET", "/system/tls")
        return TlsCertificateStatus.model_validate(response.json())


class AsyncSystem(AsyncResource):
    """Asynchronous ``system`` resource."""

    async def health(self) -> HealthResponse:
        """Async variant of :meth:`System.health`."""
        response = await self._transport.request("GET", "/health")
        body = response.json()
        if isinstance(body, dict):
            return HealthResponse.model_validate(body)
        return HealthResponse(status=str(body))

    async def get_certificate(self) -> TlsCertificateStatus:
        """Async variant of :meth:`System.get_certificate`."""
        response = await self._transport.request("GET", "/system/certificate")
        return TlsCertificateStatus.model_validate(response.json())

    async def download_certificate(self) -> bytes:
        """Async variant of :meth:`System.download_certificate`."""
        response = await self._transport.request(
            "GET", "/system/certificate/download", headers={"Accept": "*/*"}
        )
        return response.content

    async def settings(self) -> Dict[str, Any]:
        """Async variant of :meth:`System.settings`."""
        response = await self._transport.request("GET", "/system/settings")
        result: Dict[str, Any] = response.json()
        return result

    async def tls_status(self) -> TlsCertificateStatus:
        """Async variant of :meth:`System.tls_status`."""
        response = await self._transport.request("GET", "/system/tls")
        return TlsCertificateStatus.model_validate(response.json())
