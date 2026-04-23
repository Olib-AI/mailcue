"""Sandbox provider plugins.

Provider auto-registration happens when ``register_all_providers()`` is called,
avoiding circular imports at module load time.
"""

from __future__ import annotations


def register_all_providers() -> None:
    """Import all built-in provider packages to trigger registration."""
    import app.sandbox.providers.bandwidth
    import app.sandbox.providers.discord
    import app.sandbox.providers.mattermost
    import app.sandbox.providers.plivo
    import app.sandbox.providers.slack
    import app.sandbox.providers.telegram
    import app.sandbox.providers.telnyx
    import app.sandbox.providers.twilio
    import app.sandbox.providers.vonage
    import app.sandbox.providers.whatsapp  # noqa: F401
