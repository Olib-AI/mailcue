"""Database configuration and migration-chain regression tests."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.config import Settings
from app.db_migrate import _alembic_project_root


def _run_alembic(backend_root: Path, database: Path, *arguments: str) -> None:
    env = os.environ.copy()
    env["MAILCUE_DATABASE_URL"] = f"sqlite+aiosqlite:///{database}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=backend_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_sqlite_remains_zero_configuration_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MAILCUE_DATABASE_URL",
        "MAILCUE_DATABASE_BACKEND",
        "MAILCUE_DATABASE_HOST",
        "MAILCUE_DATABASE_USER",
        "MAILCUE_DATABASE_PASSWORD",
        "MAILCUE_DATABASE_NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    configured = Settings(_env_file=None)  # type: ignore[call-arg]
    assert configured.database_url == "sqlite+aiosqlite:////var/lib/mailcue/mailcue.db"


def test_postgres_url_is_built_without_password_interpolation() -> None:
    configured = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_backend="postgresql",
        database_host="postgres.internal",
        database_port=5433,
        database_user="mailcue-user",
        database_password="p@ss:/word",
        database_name="mailcue-prod",
        database_sslmode="verify-full",
    )
    url = make_url(configured.database_url)
    assert url.drivername == "postgresql+psycopg"
    assert url.host == "postgres.internal"
    assert url.port == 5433
    assert url.username == "mailcue-user"
    assert url.password == "p@ss:/word"
    assert url.database == "mailcue-prod"
    assert url.query["sslmode"] == "verify-full"


def test_bare_postgres_url_selects_psycopg() -> None:
    configured = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://mailcue:secret@db/mailcue",
    )
    assert make_url(configured.database_url).drivername == "postgresql+psycopg"


def test_migration_cli_finds_alembic_config_from_working_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(backend_root)

    assert _alembic_project_root() == backend_root


def test_alembic_history_builds_complete_sqlite_schema(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "migration-chain.db"
    _run_alembic(backend_root, database, "upgrade", "head")
    _run_alembic(backend_root, database, "check")

    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    assert revision == ("023_reset_mta_sts_verification",)
    assert "gpg_keys" in tables
    assert "warmup_campaign_accounts" in tables
    assert "ix_httpbin_requests_bin_created" in indexes
    assert "ix_sandbox_messages_provider_created" in indexes


def test_scale_migration_normalizes_existing_warmup_data(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "existing-data.db"
    _run_alembic(backend_root, database, "upgrade", "019_provider_aware_warmup")

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users "
            "(id, username, email, hashed_password, is_admin, is_active, created_at, "
            "totp_enabled, failed_login_attempts, max_mailboxes) "
            "VALUES ('user-1', 'admin', 'admin@example.com', 'hash', NULL, NULL, "
            "'2026-01-01', 0, 0, 5)"
        )
        connection.execute(
            "INSERT INTO warmup_accounts "
            "(id, name, email, provider, smtp_host, smtp_port, smtp_security, "
            "imap_host, imap_port, imap_security, username, password_encrypted, "
            "enabled, verified) VALUES "
            "('account-1', 'External', 'external@example.com', 'custom', "
            "'smtp.example.com', 587, 'starttls', 'imap.example.com', 993, 'ssl', "
            "'external@example.com', 'encrypted', 1, 1)"
        )
        connection.execute(
            "INSERT INTO warmup_campaigns "
            "(id, name, local_address, account_ids, status, start_daily_volume, "
            "daily_ramp, max_daily_volume, min_delay_minutes, max_delay_minutes, "
            "reply_rate, active_hour_start, active_hour_end, timezone, "
            "messages_sent_today, total_sent, total_failed) VALUES "
            "('campaign-1', 'Campaign', 'local@example.com', '[\"account-1\"]', "
            "'draft', 3, 1, 20, 30, 120, 70, 8, 20, 'UTC', 0, 0, 0)"
        )
        connection.commit()

    _run_alembic(backend_root, database, "upgrade", "head")

    with sqlite3.connect(database) as connection:
        links = connection.execute(
            "SELECT campaign_id, account_id, position FROM warmup_campaign_accounts"
        ).fetchall()
        campaign_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(warmup_campaigns)")
        }
        user_flags = connection.execute(
            "SELECT is_admin, is_active FROM users WHERE id='user-1'"
        ).fetchone()
    assert links == [("campaign-1", "account-1", 0)]
    assert "account_ids" not in campaign_columns
    assert "auto_clean_local_mailbox" in campaign_columns
    assert user_flags == (0, 1)


def test_mta_sts_migration_resets_legacy_txt_only_verification(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "mta-sts-cache.db"
    _run_alembic(backend_root, database, "upgrade", "022_gpg_tenant_ownership")

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO domains (name, created_at, mta_sts_verified) "
            "VALUES ('example.com', '2026-07-31', 1)"
        )
        connection.commit()

    _run_alembic(backend_root, database, "upgrade", "head")

    with sqlite3.connect(database) as connection:
        verified = connection.execute(
            "SELECT mta_sts_verified FROM domains WHERE name='example.com'"
        ).fetchone()
    assert verified == (0,)
