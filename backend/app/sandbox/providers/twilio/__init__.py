"""Twilio REST API sandbox provider plugin."""

from __future__ import annotations

from app.sandbox.providers.twilio.router import TwilioProvider
from app.sandbox.registry import register_provider

_provider = TwilioProvider()
register_provider(_provider)

__all__ = ["TwilioProvider"]
