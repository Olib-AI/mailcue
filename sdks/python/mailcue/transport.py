"""HTTP transport layer (sync + async).

Wraps ``httpx.Client`` / ``httpx.AsyncClient``, attaches auth and the
SDK ``User-Agent``, retries idempotent failures with exponential
backoff + jitter, and maps HTTP error codes to the typed exception
hierarchy in :mod:`mailcue.exceptions`.
"""

from __future__ import annotations

import json as _json
import random
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

import httpx

from mailcue._version import __version__
from mailcue.auth import AuthStrategy
from mailcue.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    MailcueError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TimeoutError,
    ValidationError,
)

DEFAULT_BASE_URL = "http://localhost:8088"
_API_PREFIX = "/api/v1"
_RETRY_STATUSES = frozenset({502, 503, 504})

JsonBody = Union[Dict[str, Any], List[Any]]


def _user_agent() -> str:
    return f"mailcue-python/{__version__} httpx/{httpx.__version__}"


def _full_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    if path.startswith(_API_PREFIX) or path.startswith("/.well-known"):
        return base + path
    return base + _API_PREFIX + path


def _retry_after(response: httpx.Response) -> Optional[float]:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _decode_error(response: httpx.Response) -> Tuple[str, Any, Any]:
    """Return ``(message, detail, body)`` extracted from an error response."""
    body: Any
    try:
        body = response.json()
    except (ValueError, _json.JSONDecodeError):
        text = response.text or response.reason_phrase or "Unknown error"
        return text, None, response.text
    if isinstance(body, dict):
        message = (
            body.get("error")
            or body.get("message")
            or (
                body["detail"]
                if isinstance(body.get("detail"), str)
                else f"HTTP {response.status_code}"
            )
        )
        return str(message), body.get("detail"), body
    return f"HTTP {response.status_code}", None, body


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    message, detail, body = _decode_error(response)
    if status == 400:
        raise ValidationError(message, status_code=status, detail=detail, response_body=body)
    if status == 401:
        raise AuthenticationError(message, status_code=status, detail=detail, response_body=body)
    if status == 403:
        raise AuthorizationError(message, status_code=status, detail=detail, response_body=body)
    if status == 404:
        raise NotFoundError(message, status_code=status, detail=detail, response_body=body)
    if status == 409:
        raise ConflictError(message, status_code=status, detail=detail, response_body=body)
    if status == 422:
        raise ValidationError(message, status_code=status, detail=detail, response_body=body)
    if status == 429:
        raise RateLimitError(
            message,
            retry_after=_retry_after(response),
            status_code=status,
            detail=detail,
            response_body=body,
        )
    if status >= 500:
        raise ServerError(message, status_code=status, detail=detail, response_body=body)
    raise MailcueError(message, status_code=status, detail=detail, response_body=body)


def _backoff_delay(attempt: int, base: float, cap: float) -> float:
    raw: float = min(cap, base * float(2**attempt))
    jitter: float = raw * 0.2
    delay: float = raw + random.uniform(-jitter, jitter)
    return max(0.0, delay)


class _TransportConfig:
    __slots__ = ("backoff_base", "backoff_cap", "base_url", "max_retries", "timeout", "verify")

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        max_retries: int,
        backoff_base: float,
        backoff_cap: float,
        verify: bool,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.verify = verify


class _BaseTransport:
    """Shared header construction + sleep schedule logic."""

    def __init__(self, config: _TransportConfig, auth: AuthStrategy) -> None:
        self._config = config
        self._auth = auth

    @property
    def base_url(self) -> str:
        return self._config.base_url

    def _headers(self, extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "User-Agent": _user_agent(),
            "Accept": "application/json",
        }
        headers.update(self._auth.headers())
        if extra:
            headers.update(extra)
        return headers

    def _delay(self, attempt: int) -> float:
        return _backoff_delay(
            attempt,
            base=self._config.backoff_base,
            cap=self._config.backoff_cap,
        )


class SyncTransport(_BaseTransport):
    """Synchronous HTTP transport built on ``httpx.Client``."""

    def __init__(
        self,
        config: _TransportConfig,
        auth: AuthStrategy,
        client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(config, auth)
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=config.timeout,
            verify=config.verify,
        )

    @property
    def client(self) -> httpx.Client:
        return self._client

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "SyncTransport":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json: Any = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> httpx.Response:
        url = _full_url(self._config.base_url, path)
        merged_headers = self._headers(headers)
        last_error: Optional[Exception] = None
        for attempt in range(self._config.max_retries + 1):
            try:
                response = self._client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=merged_headers,
                )
            except httpx.TimeoutException as exc:
                last_error = TimeoutError(f"Request to {url} timed out: {exc}")
                if attempt >= self._config.max_retries:
                    raise last_error from exc
                time.sleep(self._delay(attempt))
                continue
            except httpx.NetworkError as exc:
                last_error = NetworkError(f"Network error contacting {url}: {exc}")
                if attempt >= self._config.max_retries:
                    raise last_error from exc
                time.sleep(self._delay(attempt))
                continue

            if response.status_code in _RETRY_STATUSES and attempt < self._config.max_retries:
                response.close()
                time.sleep(self._delay(attempt))
                continue

            _raise_for_status(response)
            return response

        # Defensive: loop only exits via return or raise; unreachable in practice.
        if last_error is not None:
            raise last_error
        raise MailcueError("Request failed without explicit error")  # pragma: no cover

    def open_stream(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> "httpx.Response":
        url = _full_url(self._config.base_url, path)
        merged_headers = self._headers(headers)
        request = self._client.build_request(
            method,
            url,
            params=params,
            headers=merged_headers,
            timeout=httpx.Timeout(timeout) if timeout is not None else httpx.USE_CLIENT_DEFAULT,
        )
        response = self._client.send(request, stream=True)
        if response.status_code >= 400:
            try:
                response.read()
            finally:
                response.close()
            _raise_for_status(response)
        return response


class AsyncTransport(_BaseTransport):
    """Asynchronous HTTP transport built on ``httpx.AsyncClient``."""

    def __init__(
        self,
        config: _TransportConfig,
        auth: AuthStrategy,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(config, auth)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=config.timeout,
            verify=config.verify,
        )

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "AsyncTransport":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json: Any = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> httpx.Response:
        import asyncio

        url = _full_url(self._config.base_url, path)
        merged_headers = self._headers(headers)
        last_error: Optional[Exception] = None
        for attempt in range(self._config.max_retries + 1):
            try:
                response = await self._client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=merged_headers,
                )
            except httpx.TimeoutException as exc:
                last_error = TimeoutError(f"Request to {url} timed out: {exc}")
                if attempt >= self._config.max_retries:
                    raise last_error from exc
                await asyncio.sleep(self._delay(attempt))
                continue
            except httpx.NetworkError as exc:
                last_error = NetworkError(f"Network error contacting {url}: {exc}")
                if attempt >= self._config.max_retries:
                    raise last_error from exc
                await asyncio.sleep(self._delay(attempt))
                continue

            if response.status_code in _RETRY_STATUSES and attempt < self._config.max_retries:
                await response.aclose()
                await asyncio.sleep(self._delay(attempt))
                continue

            _raise_for_status(response)
            return response

        if last_error is not None:
            raise last_error
        raise MailcueError("Request failed without explicit error")  # pragma: no cover

    async def open_stream(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> "httpx.Response":
        url = _full_url(self._config.base_url, path)
        merged_headers = self._headers(headers)
        request = self._client.build_request(
            method,
            url,
            params=params,
            headers=merged_headers,
            timeout=httpx.Timeout(timeout) if timeout is not None else httpx.USE_CLIENT_DEFAULT,
        )
        response = await self._client.send(request, stream=True)
        if response.status_code >= 400:
            try:
                await response.aread()
            finally:
                await response.aclose()
            _raise_for_status(response)
        return response


def build_config(
    *,
    base_url: Optional[str],
    timeout: float,
    max_retries: int,
    backoff_base: float,
    backoff_cap: float,
    verify: bool,
) -> _TransportConfig:
    return _TransportConfig(
        base_url=base_url or DEFAULT_BASE_URL,
        timeout=timeout,
        max_retries=max_retries,
        backoff_base=backoff_base,
        backoff_cap=backoff_cap,
        verify=verify,
    )


__all__ = [
    "DEFAULT_BASE_URL",
    "AsyncTransport",
    "JsonBody",
    "SyncTransport",
    "_TransportConfig",
    "_full_url",
    "_raise_for_status",
    "build_config",
]
