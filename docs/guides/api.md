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
POST   /api/v1/emails/validate              # Validate syntax, DNS, SMTP, disposable, catch-all risk
POST   /api/v1/emails/validate-batch        # Validate a list, with a blended bounce-rate budget
POST   /api/v1/emails/validation-feedback   # Record an organic delivery/bounce outcome
GET    /api/v1/emails/validation-calibration # Brier score and reliability bins for past scores
POST   /api/v1/emails/bounces/ingest        # Parse a raw DSN and record its outcomes
GET    /api/v1/emails/suppressed-domains    # Domains paused after too many measured bounces
POST   /api/v1/emails/send-canaries         # Stage a send behind a canary sample
GET    /api/v1/emails/send-canaries         # List staged sends
GET    /api/v1/emails/send-canaries/:id     # Inspect one staged send
POST   /api/v1/emails/send-canaries/:id/decide # Resolve now instead of waiting out the hold
POST   /api/v1/emails/send-canaries/:id/cancel # Stop before the remainder goes out
```

### Catch-all recipients

A catch-all domain accepts every recipient at RCPT time, so no probe can
establish whether the mailbox exists. The boundary MTA has no answer to give
yet: the real verdict comes later from an internal directory lookup or a second
hop, and arrives as an asynchronous bounce.

What the API does instead is narrow the question and price it.

`validate` reports which provider runs the destination, because that decides
whether an accept-all response means anything. A security gateway that does not
sync the recipient directory accepts everything and lets the backend bounce; a
provider that answers RCPT honestly only accept-alls when a catch-all route was
configured deliberately. The probe also tests several control recipients of
different shapes, so a destination that validates recipients can be told apart
from one that accepts blindly, and `mailbox.selective_recipient_validation`
reports which it was.

`catch_all_risk.score` is a hard-bounce probability, not a label. It starts
from the receiving provider's rate, is refined by outcomes observed at that
provider and at that domain, and is then adjusted for the local part and for
passive domain signals. `contributions` itemises every adjustment.
`validation-calibration` measures whether those probabilities held up.

The largest term is usually `probe_timing`. Comparing how long the destination
took to answer for the real recipient against how long it took for recipients
known not to exist reveals whether a mailbox lookup happened at all, and on a
314-address cohort with 45 confirmed hard bounces that separated the list
better than every other signal combined: holding the domain constant,
recipients whose answer was slower than the controls bounced at 2.9% while the
rest bounced at 44.1%. `target_latency_ms` and `control_median_latency_ms` are
returned on batch results so the comparison can be audited.

Provider priors are deliberately close together. An earlier version spread
them from 0.05 to 0.35 based on how each receiver was expected to treat
unknown recipients; measurement contradicted that, so the priors were
compressed around the observed base rate and the ranking left to the probe.

`validate-batch` is the better entry point for a list. Addresses at a shared
domain reveal that domain's naming convention and any generated name variants,
neither of which is visible one address at a time. Pass `target_bounce_rate`
and the response also carries the largest subset whose blended expected bounce
rate stays under that ceiling, which is what receivers actually judge.

### Staged sending

Nothing can recall a message once it leaves the MTA. Gmail's undo is a
client-side delay before handoff, and Exchange recall only works inside one
organisation. The only real control is how much of a batch is committed at
once.

`send-canaries` sends a small sample first, watches the bounce window, then
releases the rest. The sample spans the batch's risk range rather than being
drawn from the safe end, so three outcomes can be distinguished: a clean sample
releases everything, a wholly failed sample withholds everything, and a partly
failed sample releases only the addresses scored safer than the ones that
bounced. Domains whose measured hard-bounce rate crosses the limit are added to
`suppressed-domains`, so the first tenant to find a bad domain protects the
rest.

## Mailboxes

```
GET    /api/v1/mailboxes                          # List all mailboxes with counts
POST   /api/v1/mailboxes                          # Create mailbox (admin only)
DELETE /api/v1/mailboxes/:address                  # Delete mailbox (admin only)
GET    /api/v1/mailboxes/:id/stats                 # Folder statistics
GET    /api/v1/mailboxes/:address/emails           # List emails in mailbox
GET    /api/v1/mailboxes/:address/emails/:uid      # Get specific email
GET    /api/v1/mailboxes/:address/emails/:uid/deliverability # Score deliverability
POST   /api/v1/mailboxes/:address/emails/:uid/deliverability/runs # Extended checks
DELETE /api/v1/mailboxes/:address/emails/:uid      # Delete specific email
```

Set `purpose` to `deliverability` when creating a mailbox to give it the
scored report experience in the web UI. The value defaults to `standard` and
does not change how the address receives mail.

Report history, trends, baselines, comparisons, exports, artifacts, providers,
policies, schedules, and alerts are under `/api/v1/deliverability`. See the
[deliverability testing guide](deliverability.md) for contracts and security behavior.

```json
{
  "username": "delivery-check",
  "password": "use-a-long-random-password",
  "domain": "example.com",
  "purpose": "deliverability"
}
```

The deliverability endpoint requires `email:read` and the same mailbox access
as email detail. It returns a versioned 0 to 100 score, category scores,
stable check IDs, evidence, point values, remediation, limitations, and
prioritized recommendations. The report is computed from the original message
bytes and receiver-generated authentication and spam-filter evidence.

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
