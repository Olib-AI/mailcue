"""Shared pytest fixtures: ``httpx.MockTransport`` plumbed into the SDK."""

from __future__ import annotations

from typing import Callable, Iterator, List, Tuple

import httpx
import pytest

from mailcue import AsyncMailcue, Mailcue

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def captured_requests() -> List[httpx.Request]:
    return []


@pytest.fixture
def make_client(
    captured_requests: List[httpx.Request],
) -> Iterator[Callable[[Handler], Mailcue]]:
    clients: List[Mailcue] = []

    def factory(handler: Handler) -> Mailcue:
        def wrapper(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return handler(request)

        transport = httpx.MockTransport(wrapper)
        http_client = httpx.Client(transport=transport)
        client = Mailcue(
            api_key="mc_test",
            base_url="http://test.local",
            http_client=http_client,
            max_retries=2,
            backoff_base=0.0,
            backoff_cap=0.0,
        )
        clients.append(client)
        return client

    yield factory

    for client in clients:
        client.close()


@pytest.fixture
def make_async_client(
    captured_requests: List[httpx.Request],
) -> Callable[[Handler], Tuple[AsyncMailcue, httpx.AsyncClient]]:
    def factory(handler: Handler) -> Tuple[AsyncMailcue, httpx.AsyncClient]:
        def wrapper(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return handler(request)

        transport = httpx.MockTransport(wrapper)
        http_client = httpx.AsyncClient(transport=transport)
        client = AsyncMailcue(
            api_key="mc_test",
            base_url="http://test.local",
            http_client=http_client,
            max_retries=2,
            backoff_base=0.0,
            backoff_cap=0.0,
        )
        return client, http_client

    return factory
