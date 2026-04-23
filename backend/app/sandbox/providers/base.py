"""Abstract base class for sandbox messaging providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter

if TYPE_CHECKING:
    from app.sandbox.models import SandboxMessage, SandboxProvider
    from app.sandbox.signers import SigningFn


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
    async def format_outbound_response(self, message: SandboxMessage) -> dict[str, Any]:
        """Format a stored message into the provider's native response shape."""
        ...

    @abstractmethod
    async def build_webhook_payload(
        self, message: SandboxMessage, event_type: str
    ) -> dict[str, Any] | list[Any]:
        """Build a webhook payload mimicking the provider's real webhook format.

        May return either a dict (most providers) or a list (Bandwidth, which
        delivers arrays of events).  The return value is serialised by the
        webhook worker using the content-type declared by
        :meth:`webhook_content_type`.
        """
        ...

    @abstractmethod
    async def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        """Validate that the supplied credentials dict has the required keys."""
        ...

    @abstractmethod
    def get_sandbox_url_hint(self, provider: SandboxProvider) -> str:
        """Return a URL hint that developers can use to configure their apps."""
        ...

    # ── Optional hooks with sane defaults ─────────────────────────────────

    def webhook_content_type(
        self, message: SandboxMessage, event_type: str
    ) -> Literal["json", "form"]:
        """Return the payload encoding this provider uses for webhooks.

        Twilio, Plivo, and (optionally) Bandwidth deliver inbound SMS as
        ``application/x-www-form-urlencoded``; Vonage and Telnyx always
        deliver JSON.  Individual plugins override this when they need
        per-event tuning; the default is ``"json"``.
        """
        del message, event_type
        return "json"

    def build_webhook_signer(
        self,
        *,
        message: SandboxMessage,
        provider_record: SandboxProvider,
        url: str,
        payload_body: bytes,
    ) -> SigningFn | None:
        """Return a provider-specific signer for the given webhook delivery.

        Default implementation returns ``None`` — the worker will post the
        payload unsigned.  Override in plugins that need HMAC/JWT/Basic-auth
        headers.  The signer is a coroutine ``(headers, body) -> headers``;
        it may consume the pre-serialised ``payload_body`` to compute a
        digest (e.g. Plivo's V3 signature).
        """
        del message, provider_record, url, payload_body
        return None
