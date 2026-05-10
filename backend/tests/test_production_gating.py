"""Tests for the production-mode feature gating.

Three test-only features must NOT run on a public mail server:

  * ``/api/v1/emails/inject`` and ``/api/v1/emails/bulk-inject`` — bypass
    SMTP/DKIM/SPF and APPEND straight to IMAP.  In production an admin
    could fabricate "delivered" mail without ever passing the auth path.
  * ``/sandbox/*`` and ``/api/v1/sandbox`` — emulators of third-party
    SMS/voice/IM provider APIs.  No real mail server should be exposing
    fake Twilio/Bandwidth/Telnyx endpoints to the internet.
  * ``/httpbin/*`` and the management API — request-echo service for
    local debugging only.

The conditional registration in ``app.main`` and the ``/inject`` route
guard are mirrored in ``ProductionStatusResponse.features`` so the UI
can hide menu items.  These tests pin both sides.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.config import settings
from app.emails.router import _require_non_production


def test_require_non_production_raises_when_is_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "mode", "production", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        _require_non_production()
    assert exc_info.value.status_code == 404


def test_require_non_production_passes_in_test_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "mode", "test", raising=False)
    # Should not raise.
    _require_non_production()


async def test_production_status_exposes_feature_flags(client: AsyncClient) -> None:
    """The endpoint must surface a ``features`` map so the UI knows what
    to render — without it the sidebar would dead-link to 404s in
    production."""
    resp = await client.get("/api/v1/system/production-status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    features = body["features"]
    # Default test mode: all three test-only features are available.
    assert features["inject"] is True
    assert features["messaging_sandbox"] is True
    assert features["httpbin"] is True


async def test_inject_route_guarded_by_dependency(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flipping ``settings.mode`` to production at runtime must make the
    inject endpoints 404 — proving the dependency is wired and not
    just declared."""
    monkeypatch.setattr(settings, "mode", "production", raising=False)
    resp = await client.post(
        "/api/v1/emails/inject",
        json={
            "mailbox": "anyone@example.com",
            "from_address": "sender@example.com",
            "subject": "x",
            "body": "x",
        },
    )
    assert resp.status_code == 404

    bulk = await client.post(
        "/api/v1/emails/bulk-inject",
        json={"emails": []},
    )
    assert bulk.status_code == 404


def test_create_app_starts_cleanly_in_production_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: ``create_app()`` must not raise when the sandbox/httpbin
    blocks are skipped.

    The original gating (v2.0.6) had a ``from fastapi.responses import
    FileResponse, PlainTextResponse`` *inside* the sandbox-only block.
    Python treats any name assigned anywhere in a function as local to
    that function, so when the block was skipped in production the
    later ``@app.get(... response_class=PlainTextResponse ...)`` decorator
    raised ``UnboundLocalError`` — every prod container crashed on boot
    and nginx returned 502 for every request.

    Sandbox+httpbin both off, hosting reduced to the bare API surface, is
    exactly the production deployment shape, so import the create_app
    factory fresh under those flags and assert it returns an app."""
    monkeypatch.setattr(settings, "mode", "production", raising=False)
    monkeypatch.setattr(settings, "sandbox_enabled", False, raising=False)

    from app.main import create_app

    app = create_app()
    # If we got here at all the bug is fixed; the route count assertion
    # is a sanity check that something was actually registered.
    assert len(app.routes) > 0
