"""Telnyx sandbox provider plugin."""

from __future__ import annotations

from app.sandbox.providers.telnyx.router import TelnyxProvider
from app.sandbox.registry import register_provider

_provider = TelnyxProvider()
register_provider(_provider)

__all__ = ["TelnyxProvider"]
