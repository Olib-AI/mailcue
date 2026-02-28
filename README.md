<p align="center">
  <br />
  <strong>MailCue</strong>
  <br />
  <em>A realistic email testing server in a single Docker container.</em>
  <br /><br />
  <a href="https://github.com/Olib-AI/mailcue/actions"><img src="https://img.shields.io/github/actions/workflow/status/Olib-AI/mailcue/ci.yml?branch=main&style=flat-square&label=CI" alt="CI" /></a>
  <a href="https://github.com/Olib-AI/mailcue/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="MIT License" /></a>
  <a href="https://hub.docker.com/r/olibakram/mailcue"><img src="https://img.shields.io/docker/image-size/olibakram/mailcue?style=flat-square&label=image%20size" alt="Docker Image Size" /></a>
  <a href="https://www.olib.ai"><img src="https://img.shields.io/badge/by-Olib%20AI-6c47ff?style=flat-square" alt="Olib AI" /></a>
</p>

---

MailCue is an all-in-one email testing server that packages **Postfix**, **Dovecot**, **OpenDKIM**, a **FastAPI** REST API, and a **React** web UI into a single Docker container managed by **s6-overlay**. Unlike simple SMTP catchers, MailCue provides a fully-featured mail stack -- complete with IMAP/POP3 access, DKIM signing, TLS, GPG encryption, and a modern web interface -- so you can test email workflows exactly as they will behave in production.

## Features

| Category | What you get |
|---|---|
| **Catch-all SMTP** | Accepts mail for *any* address on *any* domain. Nothing leaves the container. |
| **Full IMAP & POP3** | Read captured emails with any standard client (Thunderbird, mutt, your own code). |
| **Modern Web UI** | Responsive React app with mailbox sidebar, folder navigation, rich email viewer, and compose dialog. |
| **REST API** | Complete JSON API for sending, receiving, injecting, searching, and deleting emails -- ideal for CI pipelines. |
| **Email Injection** | Bypass SMTP entirely -- insert emails directly into mailboxes via IMAP APPEND for deterministic test setup. |
| **Bulk Injection** | Seed mailboxes with hundreds of test emails in a single API call. |
| **DKIM Signing** | Automatic DKIM key generation and signing via OpenDKIM so you can validate DKIM verification logic. |
| **TLS Everywhere** | Auto-generated self-signed certificates for SMTP STARTTLS, IMAPS (993), POP3S (995). |
| **GPG / PGP-MIME** | Generate, import, and manage GPG keys per mailbox. Sign, encrypt, verify, and decrypt emails (RFC 3156). |
| **Real-time Events** | Server-Sent Events (SSE) stream pushes `email.received`, `email.deleted`, `mailbox.created`, and more. |
| **API Keys** | Programmatic `X-API-Key` authentication for CI/CD and automation alongside JWT for the web UI. |
| **Admin Panel** | Create and delete mailboxes, inject test emails, manage GPG keys -- all from the browser. |
| **Single Container** | One `docker run` command. No external databases, no Redis, no message queues. |
| **Persistent Storage** | SQLite database and Maildir storage survive container restarts via Docker volumes. |

## Tech Stack

### Backend

- **Python 3.12** with **FastAPI** and **Uvicorn** (async)
- **SQLAlchemy 2** (async) + **aiosqlite** (SQLite by default, swappable to PostgreSQL)
- **Alembic** for database migrations
- **Argon2id** password hashing, **JWT** (HS256) authentication
- **aioimaplib** and **aiosmtplib** for async IMAP/SMTP operations
- **python-gnupg** for GPG key management and PGP/MIME operations
- **sse-starlette** for Server-Sent Events

### Frontend

- **React 19** with **TypeScript**
- **Vite 6** build tool with SWC
- **Tailwind CSS 4** for styling
- **TanStack React Query** for server-state management
- **React Router 7** for client-side routing
- **Tiptap** rich text editor for composing HTML emails
- **Zustand** for UI state
- **Zod** + **React Hook Form** for validation

### Infrastructure

- **Postfix** -- SMTP server (ports 25 and 587)
- **Dovecot** -- IMAP/POP3/LMTP server (ports 143, 993, 110, 995)
- **OpenDKIM** -- DKIM signing and verification
- **Nginx** -- Reverse proxy and static file server
- **s6-overlay v3** -- Process supervisor (PID 1)
- **Debian Bookworm** slim base image

## Architecture

```
                          +------- Single Docker Container -------+
                          |                                        |
  Port 80 ───────────────>|  Nginx                                 |
    /api/* ──────────────>|    ├── proxy_pass ──> Uvicorn (:8000)  |
    /* (SPA) ────────────>|    └── static files (/var/www/mailcue) |
                          |                                        |
  Port 25 ───────────────>|  Postfix (SMTP inbound)                |
  Port 587 ──────────────>|  Postfix (Submission w/ STARTTLS+AUTH) |
                          |    └── LMTP ──> Dovecot                |
                          |    └── milter ──> OpenDKIM             |
                          |                                        |
  Port 143 / 993 ────────>|  Dovecot (IMAP / IMAPS)               |
  Port 110 / 995 ────────>|  Dovecot (POP3 / POP3S)               |
                          |                                        |
                          |  SQLite (/var/lib/mailcue/mailcue.db)  |
                          |  Maildir (/var/mail/vhosts/)           |
                          |  GPG keyring (/var/lib/mailcue/gpg/)   |
                          +----------------------------------------+
```

**Request flow:** Nginx serves the React SPA for all non-API routes and proxies `/api/*` to Uvicorn. The FastAPI backend talks to Dovecot via IMAP (using a master-user credential for mailbox impersonation) and to Postfix via local SMTP. All services are supervised by s6-overlay, which handles startup ordering and automatic restarts.

## Quick Start

### Docker Compose (recommended)

```bash
git clone https://github.com/Olib-AI/mailcue.git
cd mailcue
docker compose up -d
```

Open **http://localhost:8088** and log in with:
- **Username:** `admin`
- **Password:** `mailcue`

### Docker Run

```bash
docker run -d \
  --name mailcue \
  -p 8088:80 \
  -p 25:25 \
  -p 587:587 \
  -p 143:143 \
  -p 993:993 \
  -v mailcue-data:/var/mail/vhosts \
  -v mailcue-db:/var/lib/mailcue \
  -e MAILCUE_DOMAIN=mailcue.local \
  -e MAILCUE_ADMIN_PASSWORD=mailcue \
  olibakram/mailcue
```

### Verify It Works

```bash
# Health check
curl http://localhost:8088/api/v1/health

# Send a test email via SMTP
echo "Subject: Hello" | sendmail -S localhost user@mailcue.local

# Or inject via the API
curl -X POST http://localhost:8088/api/v1/emails/inject \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "mailbox": "admin@mailcue.local",
    "from_address": "test@example.com",
    "to_addresses": ["admin@mailcue.local"],
    "subject": "Hello from the API",
    "html_body": "<h1>It works!</h1>"
  }'
```

## Development Setup

### Prerequisites

- **Docker** (for the full stack) or:
- **Python 3.12+** and **Node.js 22+** (for local development)

### Backend (local)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run with auto-reload (requires a running mail server or mock)
uvicorn app.main:app --reload --port 8000
```

### Frontend (local)

```bash
cd frontend
npm install
npm run dev          # Starts Vite dev server on :3000
                     # Proxies /api/* to localhost:8000
```

### Linting & Type Checking

```bash
# Backend
cd backend
ruff check .         # Linting
ruff format .        # Formatting
mypy .               # Type checking

# Frontend
cd frontend
npm run lint         # ESLint
npm run typecheck    # TypeScript
```

### Running Tests

```bash
cd backend
pytest               # Runs async tests with pytest-asyncio
```

## Configuration

All settings are configured via environment variables prefixed with `MAILCUE_`. A `.env` file is also supported.

| Variable | Default | Description |
|---|---|---|
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
| `MAILCUE_CORS_ORIGINS` | `["*"]` | Allowed CORS origins (JSON array) |
| `MAILCUE_DEBUG` | `false` | Enable debug logging |

## Exposed Ports

| Port | Protocol | Description |
|---|---|---|
| **80** | HTTP | Web UI + API (Nginx reverse proxy) |
| **25** | SMTP | Inbound mail (MTA-to-MTA, no auth required) |
| **587** | SMTP | Submission (STARTTLS + SASL authentication) |
| **143** | IMAP | IMAP with STARTTLS |
| **993** | IMAPS | IMAP over implicit TLS |
| **110** | POP3 | POP3 with STARTTLS |
| **995** | POP3S | POP3 over implicit TLS |

## API Reference

The API is served under `/api/v1` and documented with interactive Swagger UI at `/api/docs`.

### Authentication

```
POST /api/v1/auth/login          # Username + password -> JWT tokens
POST /api/v1/auth/refresh         # Refresh token rotation
POST /api/v1/auth/logout          # Clear refresh cookie
GET  /api/v1/auth/me              # Current user profile
POST /api/v1/auth/register        # Create user (admin only)
POST /api/v1/auth/api-keys        # Generate API key
GET  /api/v1/auth/api-keys        # List API keys
DELETE /api/v1/auth/api-keys/:id  # Revoke API key
```

Authenticate with either:
- `Authorization: Bearer <jwt>` header
- `X-API-Key: mc_...` header

### Emails

```
GET    /api/v1/emails              # List emails (paginated, searchable)
GET    /api/v1/emails/:uid         # Get email detail (full body + headers)
GET    /api/v1/emails/:uid/raw     # Download raw .eml file
GET    /api/v1/emails/:uid/attachments/:part_id  # Download attachment
POST   /api/v1/emails/send         # Send via SMTP (with optional GPG sign/encrypt)
POST   /api/v1/emails/inject       # Inject directly via IMAP APPEND
POST   /api/v1/emails/bulk-inject  # Batch inject multiple emails
DELETE /api/v1/emails/:uid         # Delete email
```

### Mailboxes

```
GET    /api/v1/mailboxes                          # List all mailboxes with counts
POST   /api/v1/mailboxes                          # Create mailbox (admin only)
DELETE /api/v1/mailboxes/:address                  # Delete mailbox (admin only)
GET    /api/v1/mailboxes/:id/stats                 # Folder statistics
GET    /api/v1/mailboxes/:address/emails           # List emails in mailbox
GET    /api/v1/mailboxes/:address/emails/:uid      # Get specific email
DELETE /api/v1/mailboxes/:address/emails/:uid      # Delete specific email
```

### GPG Keys

```
POST   /api/v1/gpg/keys/generate    # Generate RSA or ECC keypair
POST   /api/v1/gpg/keys/import      # Import armored PGP key
GET    /api/v1/gpg/keys              # List all keys
GET    /api/v1/gpg/keys/:address     # Get key by mailbox address
GET    /api/v1/gpg/keys/:address/export      # Export public key (JSON)
GET    /api/v1/gpg/keys/:address/export/raw  # Download .asc file
DELETE /api/v1/gpg/keys/:address     # Delete keys for address
```

### Events & Health

```
GET  /api/v1/events/stream    # SSE stream (real-time notifications)
GET  /api/v1/health           # Health check endpoint
```

**SSE event types:** `email.received`, `email.sent`, `email.deleted`, `mailbox.created`, `mailbox.deleted`, `heartbeat`

## Web UI

The frontend provides three main views:

- **Mail** -- Two-panel email client with mailbox sidebar, folder navigation (Inbox, Sent, Drafts, Trash), email list with search, and rich email detail view with HTML rendering, raw headers, attachment downloads, and GPG verification badges.
- **Compose** -- Dialog for sending emails via SMTP with a rich text editor (Tiptap), CC support, and optional GPG signing/encryption.
- **Admin** -- Tabbed panel for mailbox management (create/delete), email injection with custom headers, and GPG key management (generate/import/export/delete).

Real-time updates are delivered via SSE -- new emails appear instantly with toast notifications, and mailbox counts update automatically.

## Using with Email Clients

MailCue works with any standard email client. Configure your client with:

| Setting | Value |
|---|---|
| **IMAP Server** | `localhost` (port 143 or 993 for SSL) |
| **POP3 Server** | `localhost` (port 110 or 995 for SSL) |
| **SMTP Server** | `localhost` (port 587, STARTTLS) |
| **Username** | `admin@mailcue.local` (or any created mailbox) |
| **Password** | Your mailbox password |
| **Security** | Accept the self-signed certificate |

## Using in CI/CD

MailCue is designed for automated testing pipelines:

```yaml
# GitHub Actions example
services:
  mailcue:
    image: olibakram/mailcue
    ports:
      - 8088:80
      - 25:25
      - 143:143

steps:
  - name: Wait for MailCue
    run: |
      until curl -sf http://localhost:8088/api/v1/health; do sleep 1; done

  - name: Run email tests
    run: npm test
    env:
      SMTP_HOST: localhost
      SMTP_PORT: 25
      MAILCUE_API: http://localhost:8088/api/v1
```

Use API keys for non-interactive authentication:

```bash
# Create an API key
TOKEN=$(curl -s -X POST http://localhost:8088/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"mailcue"}' | jq -r .access_token)

API_KEY=$(curl -s -X POST http://localhost:8088/api/v1/auth/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"ci-pipeline"}' | jq -r .key)

# Use the API key in subsequent requests
curl -H "X-API-Key: $API_KEY" http://localhost:8088/api/v1/emails?mailbox=admin@mailcue.local
```

## Project Structure

```
mailcue/
├── backend/
│   ├── app/
│   │   ├── auth/          # Authentication (JWT, API keys, user management)
│   │   ├── emails/        # Email CRUD (IMAP fetch, SMTP send, inject)
│   │   ├── events/        # SSE event bus and streaming endpoint
│   │   ├── gpg/           # GPG key management and PGP/MIME operations
│   │   ├── mailboxes/     # Mailbox CRUD and Dovecot provisioning
│   │   ├── config.py      # Pydantic settings (env var configuration)
│   │   ├── database.py    # Async SQLAlchemy engine and session
│   │   ├── dependencies.py # FastAPI auth dependencies
│   │   ├── exceptions.py  # Custom exception hierarchy
│   │   └── main.py        # Application factory and lifespan
│   ├── alembic/           # Database migrations
│   └── pyproject.toml     # Python project config (hatchling)
├── frontend/
│   ├── src/
│   │   ├── components/    # React components (UI, email, admin, GPG)
│   │   ├── hooks/         # Custom hooks (auth, emails, SSE, mailboxes)
│   │   ├── lib/           # API client, auth helpers, utilities
│   │   ├── pages/         # Route pages (mail, admin, login)
│   │   ├── stores/        # Zustand state stores
│   │   └── types/         # TypeScript type definitions
│   ├── package.json
│   └── vite.config.ts
├── rootfs/                # Container filesystem overlay
│   └── etc/
│       ├── dovecot/       # Dovecot configuration
│       ├── nginx/         # Nginx reverse proxy config
│       ├── opendkim/      # OpenDKIM signing config
│       ├── postfix/       # Postfix SMTP config
│       └── s6-overlay/    # s6 service definitions and init scripts
├── Dockerfile             # Multi-stage build (frontend + runtime)
├── docker-compose.yml     # Development / single-host deployment
└── .env.example           # Configuration template
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run linters and tests:
   ```bash
   # Backend
   cd backend && ruff check . && ruff format --check . && mypy .

   # Frontend
   cd frontend && npm run lint && npm run typecheck
   ```
5. Commit your changes (`git commit -m "Add my feature"`)
6. Push to your fork (`git push origin feature/my-feature`)
7. Open a Pull Request

### Development Principles

- Backend code uses strict typing (`mypy --strict`) and follows the Ruff linter rules.
- Frontend code is TypeScript-first with ESLint enforced.
- All API endpoints follow RESTful conventions and return consistent JSON error envelopes.
- New features should include appropriate SSE events for real-time UI updates.

## License

This project is licensed under the [MIT License](LICENSE).

## Links

- **Olib AI** -- [www.olib.ai](https://www.olib.ai)
- **GitHub** -- [github.com/Olib-AI/mailcue](https://github.com/Olib-AI/mailcue)
- **API Docs** -- Available at `/api/docs` when running
- **Issues** -- [github.com/Olib-AI/mailcue/issues](https://github.com/Olib-AI/mailcue/issues)

---

<p align="center">
  Built with care by <a href="https://www.olib.ai">Olib AI</a>
</p>
