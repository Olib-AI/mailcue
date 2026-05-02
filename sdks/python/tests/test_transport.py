"""Tests for retry / backoff / error mapping."""

from __future__ import annotations

import httpx
import pytest

from mailcue import (
    AuthenticationError,
    AuthorizationError,
    Mailcue,
    MailcueError,
    NetworkError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from mailcue.exceptions import TimeoutError as MailcueTimeoutError


def _make_client(
    handler,  # type: ignore[no-untyped-def]
    *,
    max_retries: int = 2,
) -> Mailcue:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return Mailcue(
        api_key="mc_test",
        base_url="http://test.local",
        http_client=http_client,
        max_retries=max_retries,
        backoff_base=0.0,
        backoff_cap=0.0,
    )


def test_retry_on_503_then_success() -> None:
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"status": "ok"})

    client = _make_client(handler, max_retries=3)
    try:
        client.system.health()
    finally:
        client.close()
    assert calls["n"] == 3


def test_no_retry_on_400_validation() -> None:
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad input"})

    client = _make_client(handler)
    try:
        with pytest.raises(ValidationError):
            client.system.health()
    finally:
        client.close()
    assert calls["n"] == 1


def test_429_raises_with_retry_after() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"}, headers={"Retry-After": "12"})

    client = _make_client(handler)
    try:
        with pytest.raises(RateLimitError) as excinfo:
            client.system.health()
    finally:
        client.close()
    assert excinfo.value.retry_after == 12.0


def test_401_maps_to_auth_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "missing auth"})

    client = _make_client(handler)
    try:
        with pytest.raises(AuthenticationError):
            client.system.health()
    finally:
        client.close()


def test_403_maps_to_authorization_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "admin only"})

    client = _make_client(handler)
    try:
        with pytest.raises(AuthorizationError):
            client.system.health()
    finally:
        client.close()


def test_500_after_retries_raises_server_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = _make_client(handler, max_retries=1)
    try:
        with pytest.raises(ServerError):
            client.system.health()
    finally:
        client.close()


def test_network_error_after_retries() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns fail")

    client = _make_client(handler, max_retries=1)
    try:
        with pytest.raises(NetworkError):
            client.system.health()
    finally:
        client.close()


def test_timeout_maps_to_timeout_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    client = _make_client(handler, max_retries=0)
    try:
        with pytest.raises(MailcueTimeoutError):
            client.system.health()
    finally:
        client.close()


def test_validation_detail_passthrough() -> None:
    detail = [{"loc": ["body", "x"], "msg": "field required"}]

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "Validation error", "detail": detail})

    client = _make_client(handler)
    try:
        with pytest.raises(ValidationError) as excinfo:
            client.system.health()
    finally:
        client.close()
    assert excinfo.value.detail == detail


def test_unknown_4xx_falls_back_to_base_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(418, json={"error": "i am a teapot"})

    client = _make_client(handler)
    try:
        with pytest.raises(MailcueError):
            client.system.health()
    finally:
        client.close()
