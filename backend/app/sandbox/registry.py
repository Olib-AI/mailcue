"""Provider plugin registry for the messaging sandbox."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.sandbox.providers.base import BaseSandboxProvider

logger = logging.getLogger("mailcue.sandbox")

_registry: dict[str, Any] = {}


def register_provider(provider: BaseSandboxProvider) -> None:
    """Register a provider plugin by its ``provider_name``."""
    name = provider.provider_name
    if name in _registry:
        logger.warning("Overwriting existing sandbox provider '%s'", name)
    _registry[name] = provider
    logger.info("Registered sandbox provider '%s'", name)


def get_provider(name: str) -> BaseSandboxProvider | None:
    """Look up a registered provider plugin by name."""
    return _registry.get(name)


def get_all_providers() -> dict[str, BaseSandboxProvider]:
    """Return a shallow copy of the full provider registry."""
    return dict(_registry)
