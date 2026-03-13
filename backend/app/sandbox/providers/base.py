"""Abstract base class for sandbox messaging providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from app.sandbox.models import SandboxMessage, SandboxProvider


class BaseSandboxProvider(ABC):
    """Contract that every sandbox messaging provider must implement.

    Each provider plugin exposes its own FastAPI router (e.g. for receiving
    webhook callbacks from the external service) and knows how to format
    outbound responses and webhook payloads in the provider's native format.
    """

    provider_name: str  # "telegram", "slack", etc.

    @abstractmethod
    def get_router(self) -> APIRouter:
        """Return a FastAPI router with provider-specific endpoints."""
        ...

    @abstractmethod
    async def format_outbound_response(self, message: SandboxMessage) -> dict:
        """Format a stored message into the provider's native response shape."""
        ...

    @abstractmethod
    async def build_webhook_payload(self, message: SandboxMessage, event_type: str) -> dict:
        """Build a webhook payload mimicking the provider's real webhook format."""
        ...

    @abstractmethod
    async def validate_credentials(self, credentials: dict) -> bool:
        """Validate that the supplied credentials dict has the required keys."""
        ...

    @abstractmethod
    def get_sandbox_url_hint(self, provider: SandboxProvider) -> str:
        """Return a URL hint that developers can use to configure their apps."""
        ...
