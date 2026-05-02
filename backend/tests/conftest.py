"""Shared test fixtures for sandbox e2e tests.

Uses an in-memory SQLite database with a shared connection pool and
httpx.AsyncClient to exercise the full FastAPI application.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture()
async def _engine_and_session():
    """Create a single in-memory SQLite engine shared across all connections.

    ``StaticPool`` ensures the same underlying connection is reused so that
    tables created in ``create_all`` are visible to every session.
    """
    # Ensure all models are registered on Base.metadata before create_all.
    import app.auth.models
    import app.domains.models
    import app.gpg.models
    import app.mailboxes.models
    import app.sandbox.models
    import app.system.models
    import app.tunnels.models  # noqa: F401
    from app.sandbox.seeds.available_numbers import reset_pool

    reset_pool()

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    yield engine, factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def client(_engine_and_session) -> AsyncIterator[AsyncClient]:
    """Provide an httpx AsyncClient wired to the test database."""
    _engine, factory = _engine_and_session

    from app.auth.models import User
    from app.dependencies import get_current_user
    from app.main import app

    # Create a test user directly in the database
    test_user = User(
        id="test-user-id",
        username="testadmin",
        email="testadmin@mailcue.local",
        hashed_password="unused",
        is_admin=True,
        is_active=True,
    )
    async with factory() as session:
        session.add(test_user)
        await session.commit()

    # Override dependencies
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    async def _override_get_current_user() -> User:
        return test_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Provider helper fixtures ─────────────────────────────────────


@pytest.fixture()
async def telegram_provider(client: AsyncClient) -> dict:
    """Create a Telegram sandbox provider and return its JSON response."""
    resp = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "telegram",
            "name": "Test Telegram Bot",
            "credentials": {"bot_token": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"},
        },
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
async def slack_provider(client: AsyncClient) -> dict:
    """Create a Slack sandbox provider and return its JSON response."""
    resp = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "slack",
            "name": "Test Slack Bot",
            "credentials": {
                "bot_token": "xoxb-test-token-12345",
                "signing_secret": "test-signing-secret",
            },
        },
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
async def mattermost_provider(client: AsyncClient) -> dict:
    """Create a Mattermost sandbox provider and return its JSON response."""
    resp = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "mattermost",
            "name": "Test Mattermost Bot",
            "credentials": {"access_token": "mm-test-access-token-xyz"},
        },
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
async def twilio_provider(client: AsyncClient) -> dict:
    """Create a Twilio sandbox provider and return its JSON response."""
    resp = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "twilio",
            "name": "Test Twilio Account",
            "credentials": {
                "account_sid": "ACtest1234567890abcdef",
                "auth_token": "test-auth-token-secret",
            },
        },
    )
    assert resp.status_code == 201
    return resp.json()


def basic_auth_header(username: str, password: str) -> str:
    """Build an HTTP Basic auth header value."""
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


@pytest.fixture()
async def bandwidth_provider(client: AsyncClient) -> dict:
    """Create a Bandwidth sandbox provider."""
    resp = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "bandwidth",
            "name": "Test Bandwidth Account",
            "credentials": {
                "account_id": "bw-acc-12345",
                "username": "bw-user",
                "password": "bw-secret",
                "application_id": "msg-app-1",
                "voice_application_id": "voice-app-1",
            },
        },
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
async def vonage_provider(client: AsyncClient) -> dict:
    """Create a Vonage sandbox provider."""
    resp = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "vonage",
            "name": "Test Vonage Account",
            "credentials": {
                "api_key": "abc123",
                "api_secret": "def456",
                "application_id": "app-id-1",
                "messages_token": "test-bearer-token",
            },
        },
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
async def plivo_provider(client: AsyncClient) -> dict:
    """Create a Plivo sandbox provider."""
    resp = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "plivo",
            "name": "Test Plivo Account",
            "credentials": {
                "auth_id": "MAXXXXXXXXXXX",
                "auth_token": "plivo-secret-token",
            },
        },
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
async def telnyx_provider(client: AsyncClient) -> dict:
    """Create a Telnyx sandbox provider."""
    resp = await client.post(
        "/api/v1/sandbox/providers",
        json={
            "provider_type": "telnyx",
            "name": "Test Telnyx Account",
            "credentials": {
                "api_key": "KEYABCDEF1234567890",
            },
        },
    )
    assert resp.status_code == 201
    return resp.json()
