"""Bandwidth sandbox provider plugin."""

from __future__ import annotations

from app.sandbox.providers.bandwidth.router import BandwidthProvider
from app.sandbox.registry import register_provider

_provider = BandwidthProvider()
register_provider(_provider)

__all__ = ["BandwidthProvider"]
