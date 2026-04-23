"""Plivo sandbox provider plugin."""

from __future__ import annotations

from app.sandbox.providers.plivo.router import PlivoProvider
from app.sandbox.registry import register_provider

_provider = PlivoProvider()
register_provider(_provider)

__all__ = ["PlivoProvider"]
