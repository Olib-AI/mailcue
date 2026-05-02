"""Auth header builders.

MailCue accepts either an API key (``X-API-Key: mc_...``) or a JWT bearer
token (``Authorization: Bearer ...``). The transport calls ``headers()``
on the configured strategy for each request.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict


class AuthStrategy(ABC):
    """Strategy that produces auth headers for outgoing requests."""

    @abstractmethod
    def headers(self) -> Dict[str, str]:
        """Return the headers to merge into each request."""


class ApiKeyAuth(AuthStrategy):
    """Authenticate using a MailCue API key."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty")
        self._api_key = api_key

    def headers(self) -> Dict[str, str]:
        return {"X-API-Key": self._api_key}


class BearerAuth(AuthStrategy):
    """Authenticate using a JWT bearer token."""

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("token must not be empty")
        self._token = token

    def headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}


class NoAuth(AuthStrategy):
    """No-op strategy used for unauthenticated endpoints (e.g. /health)."""

    def headers(self) -> Dict[str, str]:
        return {}
