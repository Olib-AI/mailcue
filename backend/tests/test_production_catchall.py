"""Production mode catch-all and admin mailbox quota tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.auth.models import User
from app.config import settings
from app.domains.models import Domain
from app.mailboxes.models import Mailbox
from app.mailboxes.schemas import MailboxCreateRequest
from app.mailboxes.service import (
    create_mailbox,
    get_mailbox,
    get_mailbox_by_address,
    list_mailboxes,
)
from app.system.models import ServerSettings


def _make_maildir(root: Path, address: str) -> None:
    local_part, domain = address.split("@", maxsplit=1)
    base = root / domain / local_part
    for subdir in ("cur", "new", "tmp"):
        (base / subdir).mkdir(parents=True, exist_ok=True)


async def test_production_catchall_visibility_gating(
    _engine_and_session: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _engine, factory = _engine_and_session
    monkeypatch.setattr(settings, "mail_storage_path", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "admin_user", "admin", raising=False)
    monkeypatch.setattr(settings, "mode", "production", raising=False)
    _make_maildir(tmp_path, "catchall@example.com")

    admin = User(
        id="admin-id",
        username="admin",
        email="admin@example.com",
        hashed_password="unused",
        is_admin=True,
        is_active=True,
    )
    server_settings = ServerSettings(
        id=1,
        hostname="mail.example.com",
        catch_all_enabled=False,
    )

    async with factory() as session:
        session.add_all([admin, server_settings])
        await session.commit()

        # 1. When catch_all is disabled, listing mailboxes hides catch-all mailboxes
        admin_mailboxes = await list_mailboxes(session, user=admin)
        assert len(admin_mailboxes) == 0

        # And trying to fetch it raises NotFoundError
        # (It gets discovered and stored in DB, but is hidden/unavailable)
        db_mailbox = (
            await session.execute(select(Mailbox).where(Mailbox.address == "catchall@example.com"))
        ).scalar_one_or_none()
        assert db_mailbox is not None
        assert db_mailbox.is_catchall is True

        from app.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await get_mailbox(db_mailbox.id, session)

        with pytest.raises(NotFoundError):
            await get_mailbox_by_address("catchall@example.com", session)

        # 2. When catch_all is enabled, it should be visible and fetchable
        server_settings.catch_all_enabled = True
        await session.commit()

        admin_mailboxes = await list_mailboxes(session, user=admin)
        assert len(admin_mailboxes) == 1
        assert admin_mailboxes[0].address == "catchall@example.com"

        fetched_by_id = await get_mailbox(db_mailbox.id, session)
        assert fetched_by_id.address == "catchall@example.com"

        fetched_by_address = await get_mailbox_by_address("catchall@example.com", session)
        assert fetched_by_address.address == "catchall@example.com"


async def test_admin_mailbox_quota_in_production(
    _engine_and_session: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _engine, factory = _engine_and_session
    import os

    monkeypatch.setattr(os, "chown", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(settings, "mail_storage_path", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "dovecot_users_file", str(tmp_path / "users"), raising=False)
    monkeypatch.setattr(settings, "admin_user", "admin", raising=False)
    monkeypatch.setattr(settings, "mode", "production", raising=False)
    # Configure domain.com as registered domain for production checks
    domain = Domain(name="example.com", is_active=True)

    admin = User(
        id="admin-id",
        username="admin",
        email="admin@example.com",
        hashed_password="unused",
        is_admin=True,
        is_active=True,
        max_mailboxes=5,
    )

    async with factory() as session:
        session.add_all([admin, domain])
        await session.commit()

        # Create 5 mailboxes manually for the admin
        for i in range(5):
            req = MailboxCreateRequest(
                username=f"user{i}",
                password="password123",
                domain="example.com",
            )
            await create_mailbox(req, session, user_id=admin.id)

        # The 6th manual mailbox creation should fail due to quota limit
        req_failed = MailboxCreateRequest(
            username="user5",
            password="password123",
            domain="example.com",
        )
        with pytest.raises(HTTPException) as exc_info:
            await create_mailbox(req_failed, session, user_id=admin.id)
        assert exc_info.value.status_code == 403
        assert "Mailbox quota exceeded" in exc_info.value.detail
