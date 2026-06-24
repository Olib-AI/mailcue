# API reference

The MailCue REST API is served under `/api/v1` and documented with interactive Swagger UI at `/api/docs`.

## Specs

Machine-readable specs are committed to the repo for easy import:

| Format | File | Usage |
|---|---|---|
| **OpenAPI 3.1** | [`openapi.json`](../../openapi.json) | Import into any OpenAPI-compatible tool |
| **Postman v2.1** | [`postman_collection.json`](../../postman_collection.json) | **File > Import** in Postman |

To regenerate these files after changing API routes:

```bash
cd backend && python ../scripts/export_openapi.py && python ../scripts/openapi_to_postman.py
```

## Authentication

```
POST /api/v1/auth/login          # Username + password -> JWT tokens
POST /api/v1/auth/login/2fa      # Complete login with TOTP code
POST /api/v1/auth/refresh         # Refresh token rotation
POST /api/v1/auth/logout          # Clear refresh cookie
GET  /api/v1/auth/me              # Current user profile
POST /api/v1/auth/register        # Create user (admin only)
PUT  /api/v1/auth/password        # Change password
POST /api/v1/auth/totp/setup      # Generate TOTP secret + QR code
POST /api/v1/auth/totp/confirm    # Verify code and enable 2FA
POST /api/v1/auth/totp/disable    # Disable 2FA
POST /api/v1/auth/api-keys        # Generate API key
GET  /api/v1/auth/api-keys        # List API keys
DELETE /api/v1/auth/api-keys/:id  # Revoke API key
```

Authenticate with either:
- `Authorization: Bearer <jwt>` header
- `X-API-Key: mc_...` header

## API key permissions

API keys carry scopes in `resource:action` form (for example `email:read`, `email:send`, `mailbox:read`) and an optional mailbox allow-list that limits a key to specific mailboxes. The full scope catalog is at `GET /api/v1/auth/api-keys/scopes`. Keys can be edited in place via `PATCH /api/v1/auth/api-keys/{id}` from the Profile page.

## Emails

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

## Mailboxes

```
GET    /api/v1/mailboxes                          # List all mailboxes with counts
POST   /api/v1/mailboxes                          # Create mailbox (admin only)
DELETE /api/v1/mailboxes/:address                  # Delete mailbox (admin only)
GET    /api/v1/mailboxes/:id/stats                 # Folder statistics
GET    /api/v1/mailboxes/:address/emails           # List emails in mailbox
GET    /api/v1/mailboxes/:address/emails/:uid      # Get specific email
DELETE /api/v1/mailboxes/:address/emails/:uid      # Delete specific email
```

## GPG Keys

```
POST   /api/v1/gpg/keys/generate    # Generate RSA or ECC keypair
POST   /api/v1/gpg/keys/import      # Import armored PGP key
GET    /api/v1/gpg/keys              # List all keys
GET    /api/v1/gpg/keys/:address     # Get key by mailbox address
GET    /api/v1/gpg/keys/:address/export      # Export public key (JSON)
GET    /api/v1/gpg/keys/:address/export/raw  # Download .asc file
POST   /api/v1/gpg/keys/:address/publish   # Publish to keys.openpgp.org
DELETE /api/v1/gpg/keys/:address          # Delete keys for address
```

## Aliases

```
GET    /api/v1/aliases              # List all aliases (admin only)
POST   /api/v1/aliases              # Create alias (admin only)
GET    /api/v1/aliases/:id          # Get alias detail (admin only)
PUT    /api/v1/aliases/:id          # Update alias (admin only)
DELETE /api/v1/aliases/:id          # Delete alias (admin only)
```

## Domains

```
GET    /api/v1/domains                    # List managed domains (admin only)
POST   /api/v1/domains                    # Add domain + generate DKIM (admin only)
GET    /api/v1/domains/:name              # Domain details with DNS records
DELETE /api/v1/domains/:name              # Remove domain (admin only)
POST   /api/v1/domains/:name/verify-dns   # Run live DNS verification
GET    /.well-known/mta-sts.txt            # MTA-STS policy (RFC 8461, no auth)
```

## System

```
GET  /api/v1/system/certificate           # TLS certificate metadata (no auth)
GET  /api/v1/system/certificate/download  # Download PEM certificate (no auth)
GET  /api/v1/system/settings              # Server settings (admin only)
PUT  /api/v1/system/settings              # Update server settings (admin only)
GET  /api/v1/system/tls                   # Custom TLS cert status (admin only)
PUT  /api/v1/system/tls                   # Upload custom TLS cert (admin only)
GET  /api/v1/system/production-status     # Production readiness checklist (admin only)
```

## Events & Health

```
GET  /api/v1/events/stream    # SSE stream (real-time notifications)
GET  /api/v1/health           # Health check endpoint
```

**SSE event types:** `email.received`, `email.sent`, `email.deleted`, `mailbox.created`, `mailbox.deleted`, `heartbeat`

See the main [README](../../README.md) for the rest of the documentation.
