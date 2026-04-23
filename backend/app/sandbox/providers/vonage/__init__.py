"""Vonage sandbox provider plugin."""

from __future__ import annotations

from app.sandbox.providers.vonage.router import VonageProvider
from app.sandbox.registry import register_provider

_provider = VonageProvider()
register_provider(_provider)

__all__ = ["VonageProvider"]
