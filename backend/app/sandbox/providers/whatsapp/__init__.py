"""WhatsApp Business Cloud API sandbox provider plugin."""

from __future__ import annotations

from app.sandbox.providers.whatsapp.router import WhatsAppProvider
from app.sandbox.registry import register_provider

_provider = WhatsAppProvider()
register_provider(_provider)

__all__ = ["WhatsAppProvider"]
