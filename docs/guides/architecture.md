# Architecture

How MailCue runs as a single Docker container, plus the libraries and services it is built from.

## Architecture

```mermaid
graph TB
    subgraph external["External Clients"]
        browser["Browser / HTTP Client"]
        smtp_client["SMTP Client / MTA"]
        imap_client["IMAP / POP3 Client"]
    end

    subgraph container["Single Docker Container - managed by s6-overlay"]
        direction TB

        subgraph web["Web Layer"]
            nginx["Nginx<br/><sub>:80 - Reverse Proxy</sub>"]
            spa["React SPA<br/><sub>/var/www/mailcue</sub>"]
            uvicorn["Uvicorn + FastAPI<br/><sub>:8000 - REST API + SSE</sub>"]
        end

        subgraph mail["Mail Stack"]
            postfix["Postfix<br/><sub>:25 SMTP · :587 Submission</sub>"]
            dovecot["Dovecot<br/><sub>:143/:993 IMAP · :110/:995 POP3 · LMTP</sub>"]
            opendkim["OpenDKIM<br/><sub>milter - DKIM sign/verify</sub>"]
            opendmarc["OpenDMARC<br/><sub>milter - DMARC verify</sub>"]
            spamassassin["SpamAssassin<br/><sub>spamd - spam scoring</sub>"]
            spf["policyd-spf<br/><sub>SPF checking</sub>"]
        end

        subgraph storage["Persistent Storage"]
            sqlite[("SQLite / SQLCipher<br/><sub>/var/lib/mailcue/mailcue.db</sub>")]
            maildir[("Maildir<br/><sub>/var/mail/vhosts/</sub>")]
            gpg[("GPG Keyring<br/><sub>/var/lib/mailcue/gpg/</sub>")]
        end
    end

    browser -- ":80 /*" --> nginx
    smtp_client -- ":25 / :587" --> postfix
    imap_client -- ":143/:993 / :110/:995" --> dovecot

    nginx -- "static files" --> spa
    nginx -- "/api/*" --> uvicorn

    uvicorn -- "IMAP<br/><sub>master-user</sub>" --> dovecot
    uvicorn -- "local SMTP" --> postfix
    uvicorn --> sqlite
    uvicorn --> gpg

    postfix -- "LMTP" --> dovecot
    postfix -- "milter" --> opendkim
    postfix -- "milter" --> opendmarc
    postfix -- "policy" --> spf
    postfix -- "spamc" --> spamassassin

    dovecot --> maildir

    style container fill:none,stroke:#6c47ff,stroke-width:2px,color:#6c47ff
    style web fill:none,stroke:#3b82f6,stroke-width:1px
    style mail fill:none,stroke:#f59e0b,stroke-width:1px
    style storage fill:none,stroke:#10b981,stroke-width:1px
    style external fill:none,stroke:#94a3b8,stroke-width:1px,stroke-dasharray:5 5
```

**Request flow:** Nginx serves the React SPA for all non-API routes and proxies `/api/*` to Uvicorn. The FastAPI backend talks to Dovecot via IMAP (using a master-user credential for mailbox impersonation) and to Postfix via local SMTP. All services are supervised by s6-overlay, which handles startup ordering and automatic restarts.

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
- **Vite 8** build tool with SWC
- **Tailwind CSS 4** for styling
- **TanStack React Query** for server-state management
- **React Router 7** for client-side routing
- **Tiptap** rich text editor for composing HTML emails
- **Zustand** for UI state
- **Zod** + **React Hook Form** for validation

### Infrastructure

- **Postfix**: SMTP server (ports 25 and 587)
- **Dovecot**: IMAP/POP3/LMTP server (ports 143, 993, 110, 995)
- **OpenDKIM**: DKIM signing and verification
- **OpenDMARC**: DMARC policy verification (milter)
- **SpamAssassin**: Spam scoring and filtering
- **postfix-policyd-spf-python**: SPF record verification
- **Nginx**: Reverse proxy and static file server
- **s6-overlay v3**: Process supervisor (PID 1)
- **SQLCipher**: Optional AES-256 database encryption (drop-in SQLite replacement)
- **Debian Bookworm** slim base image
