"""Tests for email search criteria building, scoping, and IMAP timeout handling.

Addresses issue #309:
- IMAP TEXT search scans message bodies sequentially and causes timeouts without Dovecot FTS.
- Header search (SUBJECT, FROM, TO, CC) is the default for fast inbox search.
- Queries can be prefixed (subject:, from:, to:, body:, text:) or use search_scope="all".
- IMAP timeouts map to 504 Gateway Timeout rather than 500 Internal Server Error.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.emails import service as email_service
from app.emails.service import _build_imap_search_criteria
from app.exceptions import MailServerTimeoutError
from app.main import app

# ── Criteria building unit tests ────────────────────────────────


def test_search_criteria_empty() -> None:
    assert _build_imap_search_criteria(None) == "ALL"
    assert _build_imap_search_criteria("") == "ALL"
    assert _build_imap_search_criteria("   ") == "ALL"


def test_search_criteria_default_headers() -> None:
    criteria = _build_imap_search_criteria("invoice")
    assert criteria == 'OR (OR (OR SUBJECT "invoice" FROM "invoice") TO "invoice") CC "invoice"'


def test_search_criteria_escaping_quotes_and_backslashes() -> None:
    criteria = _build_imap_search_criteria('test "quoted" and \\slash')
    expected = (
        'OR (OR (OR SUBJECT "test \\"quoted\\" and \\\\slash" '
        'FROM "test \\"quoted\\" and \\\\slash") '
        'TO "test \\"quoted\\" and \\\\slash") '
        'CC "test \\"quoted\\" and \\\\slash"'
    )
    assert criteria == expected


def test_search_criteria_crlf_injection_prevention() -> None:
    criteria = _build_imap_search_criteria("invoice\r\nA001 LOGOUT\n")
    assert "\r" not in criteria
    assert "\n" not in criteria
    assert 'SUBJECT "invoice A001 LOGOUT"' in criteria


def test_search_criteria_scope_all_or_body() -> None:
    assert _build_imap_search_criteria("urgent", search_scope="all") == 'TEXT "urgent"'
    assert _build_imap_search_criteria("urgent", search_scope="body") == 'TEXT "urgent"'
    assert _build_imap_search_criteria("urgent", search_scope="text") == 'TEXT "urgent"'


def test_search_criteria_prefixed_queries() -> None:
    assert _build_imap_search_criteria("subject:Quarterly Report") == 'SUBJECT "Quarterly Report"'
    assert _build_imap_search_criteria("from:alice@example.com") == 'FROM "alice@example.com"'
    assert _build_imap_search_criteria("to:bob@example.com") == 'TO "bob@example.com"'
    assert (
        _build_imap_search_criteria("body:confidential payload") == 'TEXT "confidential payload"'
    )
    assert _build_imap_search_criteria("text:secret key") == 'TEXT "secret key"'


# ── IMAP timeout handling in list_emails ─────────────────────────


class _TimingOutIMAP:
    """Stub IMAP connection that raises TimeoutError during uid_search."""

    async def select(self, _folder: str) -> tuple[str, list[Any]]:
        return "OK", []

    async def uid_search(self, _criteria: str) -> tuple[str, list[Any]]:
        raise TimeoutError("IMAP command timed out")

    async def logout(self) -> None:
        return None


async def test_list_emails_maps_timeout_to_mail_server_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _mock_connect(_mailbox: str, **_kwargs: Any) -> Any:
        return _TimingOutIMAP()

    monkeypatch.setattr(email_service, "_imap_connect", _mock_connect)

    with pytest.raises(MailServerTimeoutError) as exc_info:
        await email_service.list_emails("test@example.com", search="invoice")

    assert exc_info.value.status_code == 504
    assert "timed out" in exc_info.value.message.lower()


# ── HTTP endpoint 504 response on timeout ───────────────────────


async def test_api_search_timeout_returns_504(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _mock_list_emails(*_args: Any, **_kwargs: Any) -> Any:
        raise MailServerTimeoutError(
            "Email search or fetch timed out. Please narrow your search query."
        )

    async def _mock_verify(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr("app.mailboxes.router.list_emails", _mock_list_emails)
    monkeypatch.setattr("app.mailboxes.router.verify_mailbox_access", _mock_verify)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Generate valid token or use auth bypass if configured; let's test exception handler directly
        response = await client.get("/api/v1/mailboxes/test@example.com/emails?search=heavy-term")
        # In test mode without auth header this might be 401 if auth is checked first
        # But if auth passes it returns 504
        if response.status_code == 401:
            # Let's bypass get_auth dependency
            from app.auth.models import User
            from app.dependencies import AuthContext, get_auth

            mock_user = User(id="u1", email="test@example.com", is_admin=True)
            mock_ctx = AuthContext(user=mock_user, api_key=None)
            app.dependency_overrides[get_auth] = lambda: mock_ctx
            try:
                resp2 = await client.get(
                    "/api/v1/mailboxes/test@example.com/emails?search=heavy-term"
                )
                assert resp2.status_code == 504
                data = resp2.json()
                assert "error" in data
                assert "timed out" in data["error"].lower()
            finally:
                app.dependency_overrides.pop(get_auth, None)
        else:
            assert response.status_code == 504
            data = response.json()
            assert "error" in data
            assert "timed out" in data["error"].lower()


class _CriteriaCapturingIMAP:
    """Stub IMAP that records criteria passed to uid_search."""

    def __init__(self) -> None:
        self.last_criteria: str | None = None

    async def select(self, _folder: str) -> tuple[str, list[Any]]:
        return "OK", []

    async def uid_search(self, criteria: str) -> tuple[str, list[Any]]:
        self.last_criteria = criteria
        return "OK", [b""]

    async def logout(self) -> None:
        return None


async def test_list_emails_passes_header_criteria(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _CriteriaCapturingIMAP()

    async def _mock_connect(_mailbox: str, **_kwargs: Any) -> Any:
        return stub

    monkeypatch.setattr(email_service, "_imap_connect", _mock_connect)

    await email_service.list_emails("test@example.com", search="order")
    assert stub.last_criteria == 'OR (OR (OR SUBJECT "order" FROM "order") TO "order") CC "order"'

    await email_service.list_emails("test@example.com", search="order", search_scope="all")
    assert stub.last_criteria == 'TEXT "order"'


async def test_search_emails_uses_criteria_and_handles_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _CriteriaCapturingIMAP()

    async def _mock_connect(_mailbox: str, **_kwargs: Any) -> Any:
        return stub

    monkeypatch.setattr(email_service, "_imap_connect", _mock_connect)

    res = await email_service.search_emails("test@example.com", query="order")
    assert res == []
    assert stub.last_criteria == 'OR (OR (OR SUBJECT "order" FROM "order") TO "order") CC "order"'

    # Test timeout
    async def _mock_timeout_connect(_mailbox: str, **_kwargs: Any) -> Any:
        return _TimingOutIMAP()

    monkeypatch.setattr(email_service, "_imap_connect", _mock_timeout_connect)
    with pytest.raises(MailServerTimeoutError) as exc_info:
        await email_service.search_emails("test@example.com", query="order")
    assert exc_info.value.status_code == 504


async def test_imap_connect_passes_configured_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded_timeout: float | None = None

    class _MockIMAP4:
        def __init__(self, host: str, port: int, timeout: float = 10.0, **_kwargs: Any) -> None:
            nonlocal recorded_timeout
            recorded_timeout = timeout

        async def wait_hello_from_server(self) -> None:
            pass

        async def login(self, _user: str, _pwd: str) -> Any:
            class _Resp:
                def __init__(self) -> None:
                    self.result = "OK"
                    self.lines: list[Any] = []

            return _Resp()

    monkeypatch.setattr(
        email_service, "_ensure_dovecot_user", lambda *args, **kwargs: asyncio.sleep(0)
    )
    monkeypatch.setattr("aioimaplib.IMAP4", _MockIMAP4)

    await email_service._imap_connect("user@example.com")
    assert recorded_timeout == settings.imap_timeout
