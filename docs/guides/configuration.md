# Configuration

MailCue is configured through environment variables and exposes a fixed set of network ports.

## Environment variables

All settings are configured via environment variables prefixed with `MAILCUE_`. A `.env` file is also supported.

| Variable | Default | Description |
|---|---|---|
| `MAILCUE_MODE` | `test` | Server mode: `test` (catch-all, no auth required) or `production` (strict domains, hardened security) |
| `MAILCUE_DOMAIN` | `mailcue.local` | Primary email domain (e.g., `user@<domain>`) |
| `MAILCUE_HOSTNAME` | `mail.mailcue.local` | SMTP/IMAP hostname for TLS certificates |
| `MAILCUE_ADMIN_USER` | `admin` | Default admin username |
| `MAILCUE_ADMIN_PASSWORD` | `mailcue` | Default admin password |
| `MAILCUE_SECRET_KEY` | *(auto-generated)* | JWT signing key. Leave empty for auto-generation on first boot. |
| `MAILCUE_DB_PATH` | `/var/lib/mailcue/mailcue.db` | SQLite database file path |
| `MAILCUE_DATABASE_URL` | `sqlite+aiosqlite:///...` | Full database URL (override for PostgreSQL) |
| `MAILCUE_SMTP_HOST` | `127.0.0.1` | SMTP server address (internal) |
| `MAILCUE_SMTP_PORT` | `25` | SMTP server port (internal) |
| `MAILCUE_IMAP_HOST` | `127.0.0.1` | IMAP server address (internal) |
| `MAILCUE_IMAP_PORT` | `143` | IMAP server port (internal) |
| `MAILCUE_IMAP_MASTER_USER` | `mailcue-master` | Dovecot master user for API impersonation |
| `MAILCUE_IMAP_MASTER_PASSWORD` | `master-secret` | Dovecot master user password |
| `MAILCUE_GPG_HOME` | `/var/lib/mailcue/gpg` | GnuPG keyring directory |
| `MAILCUE_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | JWT access token lifetime |
| `MAILCUE_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | JWT refresh token lifetime |
| `MAILCUE_DATABASE_ENCRYPTION_KEY` | *(empty)* | SQLCipher encryption key. Set for AES-256 database encryption. |
| `MAILCUE_RELAY_HOST` | *(empty)* | Smarthost relay hostname of an external authenticated SMTP provider |
| `MAILCUE_RELAY_PORT` | `587` | Smarthost relay port |
| `MAILCUE_RELAY_USER` | *(empty)* | Smarthost SASL username |
| `MAILCUE_RELAY_PASSWORD` | *(empty)* | Smarthost SASL password |
| `MAILCUE_ACME_EMAIL` | *(empty)* | Email for Let's Encrypt certificate provisioning (production mode) |
| `MAILCUE_TLS_CERT_PATH` | *(empty)* | Path to externally mounted TLS certificate (PEM) |
| `MAILCUE_TLS_KEY_PATH` | *(empty)* | Path to externally mounted TLS private key (PEM) |
| `MAILCUE_SMTP_TLS` | `false` | Enable TLS for outbound SMTP connections |
| `MAILCUE_CORS_ORIGINS` | `["*"]` | Allowed CORS origins (JSON array) |
| `MAILCUE_DEBUG` | `false` | Enable debug logging |

## Exposed ports

| Port | Protocol | Description |
|---|---|---|
| **80** | HTTP | Web UI + API (Nginx reverse proxy) |
| **443** | HTTPS | Web UI + API with TLS (production mode) |
| **25** | SMTP | Inbound mail (MTA-to-MTA, no auth required) |
| **465** | SMTPS | Submission over implicit TLS (production mode) |
| **587** | SMTP | Submission (STARTTLS + SASL authentication) |
| **143** | IMAP | IMAP with STARTTLS |
| **993** | IMAPS | IMAP over implicit TLS |
| **110** | POP3 | POP3 with STARTTLS |
| **995** | POP3S | POP3 over implicit TLS |
