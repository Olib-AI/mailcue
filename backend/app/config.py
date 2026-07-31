"""Application configuration via pydantic-settings v2.

All settings are read from environment variables prefixed with ``MAILCUE_``.
A ``.env`` file in the working directory is loaded automatically when present.
"""

from __future__ import annotations

import secrets

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


def _default_secret_key() -> str:
    """Generate a random secret key when none is provided via environment."""
    return secrets.token_urlsafe(32)


class Settings(BaseSettings):
    """Centralised, type-safe application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="MAILCUE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Mode ─────────────────────────────────────────────────────
    mode: str = "test"  # "test" or "production"

    # ── Application ──────────────────────────────────────────────
    domain: str = "mailcue.local"
    secret_key: str = _default_secret_key()
    admin_user: str = "admin"
    admin_password: str = "mailcue"
    debug: bool = False

    # ── TLS / ACME ───────────────────────────────────────────────
    acme_email: str = ""
    tls_cert_path: str = ""
    tls_key_path: str = ""

    # ── Database ─────────────────────────────────────────────────
    # A full URL takes precedence.  When it is empty, setting DATABASE_HOST
    # selects PostgreSQL; otherwise MailCue keeps its zero-config SQLite default.
    database_url: str = ""
    database_backend: str = "sqlite"
    database_host: str = ""
    database_port: int = 5432
    database_user: str = ""
    database_password: str = ""
    database_name: str = "mailcue"
    database_sslmode: str = "prefer"
    database_allow_insecure_private_network: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout: float = 30.0
    database_pool_recycle: int = 1800
    database_connect_timeout: int = 10
    database_statement_timeout_ms: int = 30_000
    database_encryption_key: str = ""

    # ── Mail server ──────────────────────────────────────────────
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 25
    smtp_tls: bool = False
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
    cors_origins: list[str] = []

    # ── Sandbox ────────────────────────────────────────────────────
    sandbox_enabled: bool = True
    sandbox_webhook_timeout_seconds: int = 10
    sandbox_webhook_max_retries: int = 3

    # ── Email Validation ──────────────────────────────────────────
    validation_smtp_probe_enabled: bool = True
    validation_smtp_timeout_seconds: float = 8.0
    validation_total_timeout_seconds: float = 25.0
    validation_probe_relay_host: str = ""
    validation_probe_relay_port: int = 2525
    validation_rate_limit: str = "30/minute"

    # ── Tunnels (optional outbound relay through remote VPS edges) ─
    tunnels_config_path: str = "/etc/mailcue-sidecar/tunnels.json"
    tunnel_metrics_url: str = "http://mailcue-sidecar:9325"

    @field_validator("mode", mode="before")
    @classmethod
    def _validate_mode(cls, value: object) -> str:
        normalized = str(value).strip().lower()
        if normalized not in {"test", "production"}:
            raise ValueError("mode must be exactly 'test' or 'production'")
        return normalized

    @model_validator(mode="after")
    def _resolve_database_url(self) -> Settings:
        """Build one safe SQLAlchemy URL from either supported env style."""
        self.database_backend = self.database_backend.lower()
        if self.database_backend not in {"sqlite", "postgres", "postgresql"}:
            raise ValueError("database_backend must be sqlite or postgresql")
        if not 1 <= self.database_port <= 65_535:
            raise ValueError("database_port must be between 1 and 65535")
        if self.database_pool_size < 1 or self.database_max_overflow < 0:
            raise ValueError("database pool size must be positive and overflow non-negative")
        if self.database_pool_timeout <= 0 or self.database_pool_recycle < 0:
            raise ValueError("database pool timeout must be positive and recycle non-negative")
        if self.database_connect_timeout <= 0 or self.database_statement_timeout_ms < 0:
            raise ValueError("database timeouts must be non-negative")
        if self.validation_smtp_timeout_seconds <= 0 or self.validation_total_timeout_seconds <= 0:
            raise ValueError("validation timeouts must be positive")
        if not 1 <= self.validation_probe_relay_port <= 65_535:
            raise ValueError("validation probe relay port must be between 1 and 65535")
        if self.database_url:
            url = make_url(self.database_url)
            # Bare PostgreSQL URLs are common in hosting-provider secrets.  Use
            # psycopg explicitly so the same URL works for async runtime access
            # and synchronous Alembic migrations.
            if url.drivername in {"postgres", "postgresql"}:
                url = url.set(drivername="postgresql+psycopg")
            self.database_url = url.render_as_string(hide_password=False)
            return self

        wants_postgres = self.database_backend.lower() in {"postgres", "postgresql"}
        wants_postgres = wants_postgres or bool(self.database_host)
        if wants_postgres:
            query: dict[str, str] = {
                "application_name": "mailcue",
                "connect_timeout": str(self.database_connect_timeout),
                "options": f"-c statement_timeout={self.database_statement_timeout_ms}",
            }
            if self.database_sslmode:
                query["sslmode"] = self.database_sslmode
            self.database_url = URL.create(
                "postgresql+psycopg",
                username=self.database_user or None,
                password=self.database_password or None,
                host=self.database_host or None,
                port=self.database_port,
                database=self.database_name,
                query=query,
            ).render_as_string(hide_password=False)
        else:
            self.database_url = "sqlite+aiosqlite:////var/lib/mailcue/mailcue.db"
        return self

    def validate_production_security(self) -> None:
        """Reject unsafe settings before a production process starts."""
        if not self.is_production:
            return
        errors: list[str] = []
        if self.admin_password in {"mailcue", "CHANGE_ME_PASSWORD", "CHANGE_ME_STRONG_PASSWORD"}:
            errors.append("MAILCUE_ADMIN_PASSWORD must be changed")
        if len(self.admin_password) < 12:
            errors.append("MAILCUE_ADMIN_PASSWORD must be at least 12 characters")
        if (
            not self.secret_key
            or self.secret_key.startswith("CHANGE_ME")
            or len(self.secret_key) < 32
        ):
            errors.append("MAILCUE_SECRET_KEY must be a unique value of at least 32 characters")
        if (
            not self.imap_master_password
            or self.imap_master_password == "master-secret"
            or self.imap_master_password.startswith("CHANGE_ME")
            or len(self.imap_master_password) < 32
        ):
            errors.append(
                "MAILCUE_IMAP_MASTER_PASSWORD must be a unique value of at least 32 characters"
            )
        if "*" in self.cors_origins:
            errors.append("MAILCUE_CORS_ORIGINS must not contain '*' in production")
        if self.jwt_algorithm != "HS256":
            errors.append("MAILCUE_JWT_ALGORITHM must be HS256")
        if self.debug:
            errors.append("MAILCUE_DEBUG must be false in production")
        if self.domain.endswith(".local") or "CHANGE_ME" in self.domain or "." not in self.domain:
            errors.append("MAILCUE_DOMAIN must be a public email domain")
        if (
            self.hostname.endswith(".local")
            or "CHANGE_ME" in self.hostname
            or "." not in self.hostname
        ):
            errors.append("MAILCUE_HOSTNAME must be a public mail hostname")
        has_custom_tls = bool(self.tls_cert_path and self.tls_key_path)
        has_acme = bool(self.acme_email and "CHANGE_ME" not in self.acme_email)
        if not has_acme and not has_custom_tls:
            errors.append(
                "configure MAILCUE_ACME_EMAIL or both MAILCUE_TLS_CERT_PATH and MAILCUE_TLS_KEY_PATH"
            )
        database_url = make_url(self.database_url)
        if database_url.get_backend_name() == "postgresql":
            database_host = (database_url.host or "").lower()
            sslmode = database_url.query.get("sslmode", "")
            if (
                database_host not in {"localhost", "127.0.0.1", "::1"}
                and sslmode != "verify-full"
                and not self.database_allow_insecure_private_network
            ):
                errors.append("external PostgreSQL requires MAILCUE_DATABASE_SSLMODE=verify-full")
        if errors:
            raise ValueError("Unsafe production configuration: " + "; ".join(errors))

    @property
    def is_production(self) -> bool:
        """Return ``True`` when the server is running in production mode."""
        return self.mode == "production"


settings = Settings()
