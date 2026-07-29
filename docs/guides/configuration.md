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
| `MAILCUE_SECRET_KEY` | *(auto-generated in test mode)* | JWT and TOTP encryption key. A unique value of at least 32 characters is required in production. |
| `MAILCUE_DB_PATH` | `/var/lib/mailcue/mailcue.db` | SQLite database file path |
| `MAILCUE_DATABASE_URL` | *(empty)* | Full SQLAlchemy database URL. Takes precedence over individual PostgreSQL settings. |
| `MAILCUE_DATABASE_BACKEND` | `sqlite` | `sqlite` or `postgresql` |
| `MAILCUE_DATABASE_HOST` | *(empty)* | PostgreSQL hostname. Setting this also selects PostgreSQL. |
| `MAILCUE_DATABASE_PORT` | `5432` | PostgreSQL port |
| `MAILCUE_DATABASE_USER` | *(empty)* | PostgreSQL user |
| `MAILCUE_DATABASE_PASSWORD` | *(empty)* | PostgreSQL password |
| `MAILCUE_DATABASE_NAME` | `mailcue` | PostgreSQL database name |
| `MAILCUE_DATABASE_SSLMODE` | `prefer` | Psycopg SSL mode; use `verify-full` for hosted production databases |
| `MAILCUE_DATABASE_ALLOW_INSECURE_PRIVATE_NETWORK` | `false` | Explicitly permit PostgreSQL without verified TLS on an isolated private container network |
| `MAILCUE_MIGRATION_DATABASE_URL` | *(empty)* | Optional migration-only PostgreSQL URL for a role with DDL privileges |
| `MAILCUE_DATABASE_POOL_SIZE` | `10` | Persistent PostgreSQL connections per application worker |
| `MAILCUE_DATABASE_MAX_OVERFLOW` | `20` | Temporary connections allowed above the pool size |
| `MAILCUE_DATABASE_POOL_TIMEOUT` | `30` | Seconds to wait for a pooled connection |
| `MAILCUE_DATABASE_POOL_RECYCLE` | `1800` | Seconds before a pooled connection is replaced |
| `MAILCUE_DATABASE_CONNECT_TIMEOUT` | `10` | Seconds allowed when opening a PostgreSQL connection |
| `MAILCUE_DATABASE_STATEMENT_TIMEOUT_MS` | `30000` | PostgreSQL statement timeout in milliseconds. Set to `0` to disable it. |
| `MAILCUE_SMTP_HOST` | `127.0.0.1` | SMTP server address (internal) |
| `MAILCUE_SMTP_PORT` | `25` | SMTP server port (internal) |
| `MAILCUE_IMAP_HOST` | `127.0.0.1` | IMAP server address (internal) |
| `MAILCUE_IMAP_PORT` | `143` | IMAP server port (internal) |
| `MAILCUE_IMAP_MASTER_USER` | `mailcue-master` | Dovecot master user for API impersonation |
| `MAILCUE_IMAP_MASTER_PASSWORD` | `master-secret` in test mode | Required unique value of at least 32 characters in production |
| `MAILCUE_GPG_HOME` | `/var/lib/mailcue/gpg` | GnuPG keyring directory |
| `MAILCUE_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | JWT access token lifetime |
| `MAILCUE_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | JWT refresh token lifetime |
| `MAILCUE_DATABASE_ENCRYPTION_KEY` | *(empty)* | SQLCipher encryption key for SQLite only. PostgreSQL encryption is managed by the database provider. |
| `MAILCUE_RELAY_HOST` | *(empty)* | Smarthost relay hostname of an external authenticated SMTP provider |
| `MAILCUE_RELAY_PORT` | `587` | Smarthost relay port |
| `MAILCUE_RELAY_USER` | *(empty)* | Smarthost SASL username |
| `MAILCUE_RELAY_PASSWORD` | *(empty)* | Smarthost SASL password |
| `MAILCUE_ACME_EMAIL` | *(empty)* | Email for Let's Encrypt certificate provisioning (production mode) |
| `MAILCUE_TLS_CERT_PATH` | *(empty)* | Path to externally mounted TLS certificate (PEM) |
| `MAILCUE_TLS_KEY_PATH` | *(empty)* | Path to externally mounted TLS private key (PEM) |
| `MAILCUE_SMTP_TLS` | `false` | Enable TLS for outbound SMTP connections |
| `MAILCUE_CORS_ORIGINS` | `[]` | Exact allowed CORS origins as a JSON array. Wildcards are rejected in production. |
| `MAILCUE_DEBUG` | `false` | Enable debug logging |

## Database configuration

SQLite is the default and requires no database settings. Use it for local
development, CI, and smaller installations. Use PostgreSQL for production
installations that handle sustained concurrent requests or large metadata and
sandbox datasets.

Configure PostgreSQL with individual environment variables:

```env
MAILCUE_DATABASE_BACKEND=postgresql
MAILCUE_DATABASE_HOST=postgres
MAILCUE_DATABASE_PORT=5432
MAILCUE_DATABASE_USER=mailcue
MAILCUE_DATABASE_PASSWORD=replace-me
MAILCUE_DATABASE_NAME=mailcue
MAILCUE_DATABASE_SSLMODE=disable
MAILCUE_DATABASE_ALLOW_INSECURE_PRIVATE_NETWORK=true
```

`MAILCUE_DATABASE_HOST` also selects PostgreSQL when
`MAILCUE_DATABASE_BACKEND` is not set. Setting the backend explicitly is
recommended because it makes deployment intent clear.

Alternatively, provide one SQLAlchemy URL. The URL takes precedence over all
individual connection settings:

```env
MAILCUE_DATABASE_URL=postgresql+psycopg://mailcue:replace-me@postgres:5432/mailcue?sslmode=disable
```

Percent-encode special characters in usernames or passwords used in a URL. The
individual variables do not require URL encoding. Use `verify-full` for managed
or remote PostgreSQL with a trusted TLS certificate. Use `disable` only for a
PostgreSQL service on a trusted private Docker network or another protected
local network, and set `MAILCUE_DATABASE_ALLOW_INSECURE_PRIVATE_NETWORK=true`
to acknowledge that exception. Never use this exception for a remote host.

Pool limits apply per MailCue application process. With multiple replicas, the
maximum normal connection count is approximately `replicas * pool size`, plus
temporary overflow connections. Size the PostgreSQL connection limit with this
total in mind.

MailCue runs Alembic migrations automatically before the API starts. PostgreSQL
migrations use an advisory lock, which prevents multiple MailCue replicas from
changing the schema at the same time. Set `MAILCUE_MIGRATION_DATABASE_URL` to a
DDL-capable role and use a separate, lower-privilege `MAILCUE_DATABASE_URL` for
the running API. Existing SQLite installations require the offline copy
procedure in [Production deployment](production.md#migrate-from-sqlite-or-sqlcipher).

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
