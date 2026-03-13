"""Mattermost API v4 sandbox provider plugin."""

from __future__ import annotations

from app.sandbox.providers.mattermost.router import MattermostProvider
from app.sandbox.registry import register_provider

_provider = MattermostProvider()
register_provider(_provider)

__all__ = ["MattermostProvider"]
