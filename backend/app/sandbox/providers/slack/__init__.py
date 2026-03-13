"""Slack Web API sandbox provider plugin."""

from __future__ import annotations

from app.sandbox.providers.slack.router import SlackProvider
from app.sandbox.registry import register_provider

_provider = SlackProvider()
register_provider(_provider)

__all__ = ["SlackProvider"]
