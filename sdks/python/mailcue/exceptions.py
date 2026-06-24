"""Exception hierarchy for the MailCue SDK."""

from __future__ import annotations

from typing import Any, Optional


class MailcueError(Exception):
    """Base class for every error raised by the MailCue SDK."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        detail: Any = None,
        response_body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail
        self.response_body = response_body

    def __str__(self) -> str:
        if self.status_code is not None:
            return f"[{self.status_code}] {self.message}"
        return self.message


class NetworkError(MailcueError):
    """Connection failure, DNS error, or other transport-level network issue."""


class TimeoutError(MailcueError):
    """Request exceeded the configured timeout."""


class AuthenticationError(MailcueError):
    """HTTP 401: invalid or missing API key / bearer token."""


class AuthorizationError(AuthenticationError):
    """HTTP 403: caller authenticated but lacks required privileges."""


class PermissionDeniedError(AuthorizationError):
    """HTTP 403 caused by an API key lacking a required permission.

    Raised when the key is missing a scope (``email:send``, ``mailbox:read``,
    ...) or is not allowed to access the target mailbox. ``scope`` holds the
    missing permission when the server names one, otherwise ``None``.

    Subclasses :class:`AuthorizationError`, so existing ``except
    AuthorizationError`` handlers keep working.
    """

    def __init__(
        self,
        message: str,
        *,
        scope: Optional[str] = None,
        status_code: Optional[int] = 403,
        detail: Any = None,
        response_body: Any = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            detail=detail,
            response_body=response_body,
        )
        self.scope = scope


class NotFoundError(MailcueError):
    """HTTP 404: requested resource does not exist."""


class ConflictError(MailcueError):
    """HTTP 409: request conflicts with current resource state."""


class ValidationError(MailcueError):
    """HTTP 400 or 422: request failed server-side validation."""


class RateLimitError(MailcueError):
    """HTTP 429: caller exceeded the rate limit."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: Optional[float] = None,
        status_code: Optional[int] = 429,
        detail: Any = None,
        response_body: Any = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            detail=detail,
            response_body=response_body,
        )
        self.retry_after = retry_after


class ServerError(MailcueError):
    """HTTP 5xx: MailCue server-side failure."""
