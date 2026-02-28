"""Custom exception hierarchy and FastAPI exception handlers.

All domain errors derive from ``MailCueError`` so they can be caught and
serialised into a consistent JSON envelope by the handlers registered
with ``register_exception_handlers``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("mailcue")


# ── Base exception ───────────────────────────────────────────────


class MailCueError(Exception):
    """Base for all MailCue domain exceptions."""

    def __init__(
        self,
        message: str = "An internal error occurred",
        status_code: int = 500,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail


# ── Concrete exceptions ─────────────────────────────────────────


class NotFoundError(MailCueError):
    """Requested resource does not exist."""

    def __init__(self, resource: str = "Resource", identifier: str = "") -> None:
        msg = f"{resource} not found"
        if identifier:
            msg = f"{resource} '{identifier}' not found"
        super().__init__(message=msg, status_code=404)


class ConflictError(MailCueError):
    """Resource already exists or state conflict."""

    def __init__(self, message: str = "Resource already exists") -> None:
        super().__init__(message=message, status_code=409)


class AuthenticationError(MailCueError):
    """Invalid or missing credentials."""

    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(message=message, status_code=401)


class AuthorizationError(MailCueError):
    """Authenticated but insufficient privileges."""

    def __init__(self, message: str = "Insufficient privileges") -> None:
        super().__init__(message=message, status_code=403)


class MailServerError(MailCueError):
    """Failure communicating with Postfix / Dovecot."""

    def __init__(self, message: str = "Mail server communication error") -> None:
        super().__init__(message=message, status_code=502)


class ValidationError(MailCueError):
    """Domain-level validation failure (beyond Pydantic)."""

    def __init__(self, message: str = "Validation error", detail: Any = None) -> None:
        super().__init__(message=message, status_code=422, detail=detail)


# ── Handler registration ────────────────────────────────────────


def register_exception_handlers(app: FastAPI) -> None:
    """Attach custom exception handlers to the FastAPI application."""

    @app.exception_handler(MailCueError)
    async def _mailcue_error_handler(
        _request: Request, exc: MailCueError
    ) -> JSONResponse:
        logger.warning("MailCueError: %s (status=%d)", exc.message, exc.status_code)
        body: dict[str, Any] = {"error": exc.message}
        if exc.detail is not None:
            body["detail"] = exc.detail
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(
        _request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"},
        )
