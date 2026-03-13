"""Application configuration via pydantic-settings v2.

All settings are read from environment variables prefixed with ``MAILCUE_``.
A ``.env`` file in the working directory is loaded automatically when present.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised, type-safe application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="MAILCUE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────────
    domain: str = "mailcue.local"
    secret_key: str = "change-me-in-production"
    admin_user: str = "admin"
    admin_password: str = "mailcue"
    debug: bool = False

    # ── Database ─────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:////var/lib/mailcue/mailcue.db"
    database_encryption_key: str = ""

    # ── Mail server ──────────────────────────────────────────────
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 25
    imap_host: str = "127.0.0.1"
    imap_port: int = 143

    # Dovecot master user — enables API access to every mailbox via
    # ``user@domain*master_user`` with the master password.
    imap_master_user: str = "mailcue-master"
    imap_master_password: str = "master-secret"

    # ── JWT ───────────────────────────────────────────────────────
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # ── Dovecot / Postfix ────────────────────────────────────────
    dovecot_users_file: str = "/etc/dovecot/users"
    mail_storage_path: str = "/var/mail/vhosts"

    # ── GPG ──────────────────────────────────────────────────────
    gpg_home: str = "/var/lib/mailcue/gpg"

    # ── TOTP / 2FA ────────────────────────────────────────────────
    totp_issuer: str = "MailCue"

    # ── Account lockout ─────────────────────────────────────────
    max_failed_login_attempts: int = 5
    lockout_duration_minutes: int = 15

    # ── Rate limiting ───────────────────────────────────────────
    login_rate_limit: str = "5/minute"
    sensitive_rate_limit: str = "10/minute"

    # ── Relay / Smarthost ─────────────────────────────────────────
    relay_host: str = ""
    relay_port: int = 587
    relay_user: str = ""
    relay_password: str = ""

    # ── Hostname (used for MX verification) ─────────────────────
    hostname: str = "mail.mailcue.local"

    # ── CORS ─────────────────────────────────────────────────────
    cors_origins: list[str] = ["*"]

    # ── Sandbox ────────────────────────────────────────────────────
    sandbox_enabled: bool = True
    sandbox_webhook_timeout_seconds: int = 10
    sandbox_webhook_max_retries: int = 3


settings = Settings()
