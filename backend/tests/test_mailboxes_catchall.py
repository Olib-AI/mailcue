"""Catch-all mailbox discovery tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.auth.models import User
from app.config import settings
from app.mailboxes.models import Mailbox
from app.mailboxes.service import list_mailboxes


def _make_maildir(root: Path, address: str) -> None:
    local_part, domain = address.split("@", maxsplit=1)
    base = root / domain / local_part
    for subdir in ("cur", "new", "tmp"):
        (base / subdir).mkdir(parents=True, exist_ok=True)


async def test_catchall_discovery_assigns_new_mailbox_to_configured_admin(
    _engine_and_session: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _engine, factory = _engine_and_session
    monkeypatch.setattr(settings, "mail_storage_path", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "admin_user", "admin", raising=False)
    _make_maildir(tmp_path, "random@example.com")

    admin = User(
        id="admin-id",
        username="admin",
        email="admin@example.com",
        hashed_password="unused",
        is_admin=True,
        is_active=True,
    )
    user = User(
        id="user-id",
        username="user",
        email="user@example.com",
        hashed_password="unused",
        is_admin=False,
        is_active=True,
    )
    async with factory() as session:
        session.add_all([admin, user])
        await session.commit()

        admin_mailboxes = await list_mailboxes(session, user=admin)
        user_mailboxes = await list_mailboxes(session, user=user)

        assert [mailbox.address for mailbox in admin_mailboxes] == ["random@example.com"]
        assert admin_mailboxes[0].user_id == "admin-id"
        assert user_mailboxes == []


async def test_catchall_discovery_backfills_existing_orphan_mailbox(
    _engine_and_session: Any,
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    _engine, factory = _engine_and_session
    monkeypatch.setattr(settings, "mail_storage_path", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "admin_user", "admin", raising=False)
    _make_maildir(tmp_path, "legacy@example.com")

    admin = User(
        id="admin-id",
        username="admin",
        email="admin@example.com",
        hashed_password="unused",
        is_admin=True,
        is_active=True,
    )
    orphan = Mailbox(
        address="legacy@example.com",
        display_name="legacy",
        domain="example.com",
        user_id=None,
    )
    async with factory() as session:
        session.add_all([admin, orphan])
        await session.commit()

        admin_mailboxes = await list_mailboxes(session, user=admin)

        assert [mailbox.address for mailbox in admin_mailboxes] == ["legacy@example.com"]

        result = await session.execute(select(Mailbox).where(Mailbox.address == orphan.address))
        refreshed = result.scalar_one()
        assert refreshed.user_id == "admin-id"
