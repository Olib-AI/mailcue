"""``gpg`` resource — manage PGP keypairs per mailbox."""

from __future__ import annotations

from typing import Any, Dict, Optional

from mailcue.resources._base import AsyncResource, SyncResource
from mailcue.types import (
    GpgKey,
    GpgKeyExport,
    GpgKeyListResponse,
    KeyserverPublishResult,
)


def _generate_payload(
    mailbox_address: str,
    name: str,
    algorithm: str,
    key_length: int,
    expire: Optional[str],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "mailbox_address": mailbox_address,
        "name": name,
        "algorithm": algorithm,
        "key_length": key_length,
    }
    if expire is not None:
        payload["expire"] = expire
    return payload


class Gpg(SyncResource):
    """Synchronous ``gpg`` resource."""

    def list(self) -> GpgKeyListResponse:
        """List all GPG keys.

        Example:
            >>> client.gpg.list()
        """
        response = self._transport.request("GET", "/gpg/keys")
        return GpgKeyListResponse.model_validate(response.json())

    def generate(
        self,
        mailbox_address: str,
        *,
        name: str = "MailCue User",
        algorithm: str = "RSA",
        key_length: int = 2048,
        expire: Optional[str] = None,
    ) -> GpgKey:
        """Generate a new GPG keypair for ``mailbox_address``.

        Example:
            >>> client.gpg.generate("alice@example.com", key_length=4096)
        """
        payload = _generate_payload(mailbox_address, name, algorithm, key_length, expire)
        response = self._transport.request("POST", "/gpg/keys/generate", json=payload)
        return GpgKey.model_validate(response.json())

    def get(self, address: str) -> GpgKey:
        """Fetch the GPG key bound to a mailbox.

        Example:
            >>> client.gpg.get("alice@example.com")
        """
        response = self._transport.request("GET", f"/gpg/keys/{address}")
        return GpgKey.model_validate(response.json())

    def export_public(self, address: str) -> GpgKeyExport:
        """Export the armored public key.

        Example:
            >>> client.gpg.export_public("alice@example.com").public_key
        """
        response = self._transport.request("GET", f"/gpg/keys/{address}/export")
        return GpgKeyExport.model_validate(response.json())

    def import_key(
        self,
        armored_key: str,
        *,
        mailbox_address: Optional[str] = None,
    ) -> GpgKey:
        """Import an armored PGP key.

        Example:
            >>> client.gpg.import_key(armored_key=PEM, mailbox_address="alice@example.com")
        """
        payload: Dict[str, Any] = {"armored_key": armored_key}
        if mailbox_address is not None:
            payload["mailbox_address"] = mailbox_address
        response = self._transport.request("POST", "/gpg/keys/import", json=payload)
        return GpgKey.model_validate(response.json())

    def publish(self, address: str) -> KeyserverPublishResult:
        """Publish the public key to keys.openpgp.org.

        Example:
            >>> client.gpg.publish("alice@example.com")
        """
        response = self._transport.request("POST", f"/gpg/keys/{address}/publish")
        return KeyserverPublishResult.model_validate(response.json())

    def delete(self, address: str) -> None:
        """Delete a GPG key.

        Example:
            >>> client.gpg.delete("alice@example.com")
        """
        self._transport.request("DELETE", f"/gpg/keys/{address}")


class AsyncGpg(AsyncResource):
    """Asynchronous ``gpg`` resource."""

    async def list(self) -> GpgKeyListResponse:
        """Async variant of :meth:`Gpg.list`."""
        response = await self._transport.request("GET", "/gpg/keys")
        return GpgKeyListResponse.model_validate(response.json())

    async def generate(
        self,
        mailbox_address: str,
        *,
        name: str = "MailCue User",
        algorithm: str = "RSA",
        key_length: int = 2048,
        expire: Optional[str] = None,
    ) -> GpgKey:
        """Async variant of :meth:`Gpg.generate`."""
        payload = _generate_payload(mailbox_address, name, algorithm, key_length, expire)
        response = await self._transport.request("POST", "/gpg/keys/generate", json=payload)
        return GpgKey.model_validate(response.json())

    async def get(self, address: str) -> GpgKey:
        """Async variant of :meth:`Gpg.get`."""
        response = await self._transport.request("GET", f"/gpg/keys/{address}")
        return GpgKey.model_validate(response.json())

    async def export_public(self, address: str) -> GpgKeyExport:
        """Async variant of :meth:`Gpg.export_public`."""
        response = await self._transport.request("GET", f"/gpg/keys/{address}/export")
        return GpgKeyExport.model_validate(response.json())

    async def import_key(
        self,
        armored_key: str,
        *,
        mailbox_address: Optional[str] = None,
    ) -> GpgKey:
        """Async variant of :meth:`Gpg.import_key`."""
        payload: Dict[str, Any] = {"armored_key": armored_key}
        if mailbox_address is not None:
            payload["mailbox_address"] = mailbox_address
        response = await self._transport.request("POST", "/gpg/keys/import", json=payload)
        return GpgKey.model_validate(response.json())

    async def publish(self, address: str) -> KeyserverPublishResult:
        """Async variant of :meth:`Gpg.publish`."""
        response = await self._transport.request("POST", f"/gpg/keys/{address}/publish")
        return KeyserverPublishResult.model_validate(response.json())

    async def delete(self, address: str) -> None:
        """Async variant of :meth:`Gpg.delete`."""
        await self._transport.request("DELETE", f"/gpg/keys/{address}")
