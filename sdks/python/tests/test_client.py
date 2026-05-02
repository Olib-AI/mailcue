"""Smoke tests for the top-level client."""

from __future__ import annotations

import httpx
import pytest

from mailcue import AsyncMailcue, Mailcue, __version__


def test_default_base_url() -> None:
    client = Mailcue(api_key="mc_x")
    try:
        assert client.base_url == "http://localhost:8088"
    finally:
        client.close()


def test_rejects_both_auth_modes() -> None:
    with pytest.raises(ValueError):
        Mailcue(api_key="mc_x", bearer_token="eyJ")


def test_attaches_api_key_and_user_agent(make_client, captured_requests) -> None:  # type: ignore[no-untyped-def]
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    client = make_client(handler)
    client.system.health()

    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request.headers["x-api-key"] == "mc_test"
    assert request.headers["user-agent"].startswith(f"mailcue-python/{__version__}")
    assert request.url.path == "/api/v1/health"


def test_bearer_token_flow() -> None:
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = Mailcue(
        bearer_token="eyJabc",
        base_url="http://test.local",
        http_client=http_client,
        max_retries=0,
    )
    try:
        client.system.health()
    finally:
        client.close()
    assert captured[0].headers["authorization"] == "Bearer eyJabc"


async def test_async_client_smoke() -> None:
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    client = AsyncMailcue(
        api_key="mc_async",
        base_url="http://test.local",
        http_client=http_client,
        max_retries=0,
    )
    async with client:
        result = await client.system.health()
    assert result.status == "ok"
    assert captured[0].headers["x-api-key"] == "mc_async"
