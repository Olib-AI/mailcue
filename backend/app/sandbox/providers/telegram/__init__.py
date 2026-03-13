"""Telegram Bot API sandbox provider plugin."""

from __future__ import annotations

from app.sandbox.providers.telegram.router import TelegramProvider
from app.sandbox.registry import register_provider

_provider = TelegramProvider()
register_provider(_provider)

__all__ = ["TelegramProvider"]
