---
name: mailcue
description: "MailCue email operations via REST API: send, receive, reply, forward, delete, search, manage mailboxes and aliases. Use when: (1) sending or composing emails, (2) reading inbox or checking for new mail, (3) replying to or forwarding emails, (4) searching emails, (5) managing mailboxes or aliases. NOT for: IMAP/POP3 client operations, DNS configuration, or server administration."
metadata: {"openclaw": {"emoji": "📧", "requires": {"env": ["MAILCUE_URL", "MAILCUE_API_KEY"]}}}
---

# MailCue Email Skill

Interact with a MailCue email server via its REST API. Supports sending, receiving, replying, forwarding, deleting, searching emails, and managing mailboxes and aliases.

## When to Use

- Sending emails (with display name, CC, BCC, attachments)
- Checking inbox for new or unread emails
- Reading a specific email
- Replying to or forwarding emails (with proper threading)
- Searching emails by subject, sender, or body content
- Deleting emails or marking as read/unread
- Managing mailboxes and email aliases

## When NOT to Use

- Server setup, DNS configuration, or TLS management → use the MailCue admin UI
- Direct IMAP/POP3 access → use a mail client
- Bulk email marketing → MailCue is not a marketing platform

## Setup

Set these environment variables:

```bash
export MAILCUE_URL="https://mail.example.com"    # Your MailCue server URL
export MAILCUE_API_KEY="mc_..."                    # API key from Profile > API Keys
```

To create an API key via the API:

```bash
# Login first
TOKEN=$(curl -s -X POST $MAILCUE_URL/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"yourpassword"}' | jq -r .access_token)

# Create API key
API_KEY=$(curl -s -X POST $MAILCUE_URL/api/v1/auth/api-keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"openclaw"}' | jq -r .key)

echo "MAILCUE_API_KEY=$API_KEY"
```

## Authentication

All requests use the `X-API-Key` header:

```
X-API-Key: $MAILCUE_API_KEY
```

## API Base URL

All endpoints are under `$MAILCUE_URL/api/v1`.

---

## Email Operations

### List emails in a mailbox

```bash
curl -s "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails?folder=INBOX&page=1&page_size=20" \
  -H "X-API-Key: $MAILCUE_API_KEY"
```

Parameters:
- `{mailbox}` — Email address (e.g., `admin@example.com`)
- `folder` — `INBOX`, `Sent`, `Drafts`, `Trash`, `Spam` (default: `INBOX`)
- `search` — Search by subject/body text
- `page`, `page_size` — Pagination

Response fields: `emails[].uid`, `emails[].from_address`, `emails[].from_name`, `emails[].to_addresses`, `emails[].subject`, `emails[].date`, `emails[].is_read`, `emails[].preview`, `emails[].message_id`

### Read a specific email

```bash
curl -s "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails/{uid}" \
  -H "X-API-Key: $MAILCUE_API_KEY"
```

Response includes: `html_body`, `text_body`, `attachments[]`, `raw_headers`, `message_id`, `from_name`, `from_address`

### Send an email

```bash
curl -s -X POST "$MAILCUE_URL/api/v1/emails/send" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "from_address": "user@example.com",
    "from_name": "Display Name",
    "to_addresses": ["recipient@example.com"],
    "cc_addresses": [],
    "bcc_addresses": [],
    "subject": "Subject line",
    "body": "<p>HTML body content</p>",
    "body_type": "html"
  }'
```

Fields:
- `from_address` (required) — Sender email address
- `from_name` (optional) — Display name shown in From header
- `to_addresses` (required) — Array of recipient emails
- `cc_addresses` (optional) — CC recipients
- `bcc_addresses` (optional) — BCC recipients
- `subject` (required) — Email subject
- `body` (required) — Email body content
- `body_type` — `"html"` or `"plain"` (default: `"plain"`)

### Reply to an email

To reply, include threading headers. First read the original email to get `message_id` and `raw_headers.References`:

```bash
# 1. Get original email
ORIGINAL=$(curl -s "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails/{uid}" \
  -H "X-API-Key: $MAILCUE_API_KEY")

# 2. Extract threading info
MESSAGE_ID=$(echo $ORIGINAL | jq -r .message_id)
EXISTING_REFS=$(echo $ORIGINAL | jq -r '.raw_headers.References // ""')
FROM=$(echo $ORIGINAL | jq -r .from_address)
SUBJECT=$(echo $ORIGINAL | jq -r .subject)

# 3. Send reply with threading
curl -s -X POST "$MAILCUE_URL/api/v1/emails/send" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"from_address\": \"user@example.com\",
    \"from_name\": \"Your Name\",
    \"to_addresses\": [\"$FROM\"],
    \"subject\": \"Re: $SUBJECT\",
    \"body\": \"<p>Reply content here</p>\",
    \"body_type\": \"html\",
    \"in_reply_to\": \"$MESSAGE_ID\",
    \"references\": [\"$MESSAGE_ID\"]
  }"
```

Important threading rules:
- `in_reply_to` — The `message_id` of the email being replied to
- `references` — Array containing existing References chain + the parent's `message_id`
- `subject` — Prefix with `Re: ` for replies, `Fwd: ` for forwards

### Forward an email

```bash
# 1. Get original email
ORIGINAL=$(curl -s "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails/{uid}" \
  -H "X-API-Key: $MAILCUE_API_KEY")

# 2. Forward with original content
SUBJECT=$(echo $ORIGINAL | jq -r .subject)
BODY=$(echo $ORIGINAL | jq -r .html_body)

curl -s -X POST "$MAILCUE_URL/api/v1/emails/send" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"from_address\": \"user@example.com\",
    \"from_name\": \"Your Name\",
    \"to_addresses\": [\"forward-to@example.com\"],
    \"subject\": \"Fwd: $SUBJECT\",
    \"body\": \"<p>See forwarded message below:</p><hr>$BODY\",
    \"body_type\": \"html\"
  }"
```

### Delete an email

```bash
curl -s -X DELETE "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails/{uid}" \
  -H "X-API-Key: $MAILCUE_API_KEY"
```

First delete moves to Trash. Deleting from Trash permanently removes the email.

### Mark as read / unread

```bash
# Mark as read
curl -s -X PATCH "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails/{uid}/flags" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"seen": true}'

# Mark as unread
curl -s -X PATCH "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails/{uid}/flags" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"seen": false}'
```

### Search emails

```bash
curl -s "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails?search=meeting&folder=INBOX" \
  -H "X-API-Key: $MAILCUE_API_KEY"
```

The `search` parameter searches subject and body text via IMAP TEXT search.

### Download raw email (.eml)

```bash
curl -s "$MAILCUE_URL/api/v1/emails/{uid}/raw?mailbox={mailbox}" \
  -H "X-API-Key: $MAILCUE_API_KEY" -o email.eml
```

### Download attachment

```bash
curl -s "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails/{uid}/attachments/{part_id}" \
  -H "X-API-Key: $MAILCUE_API_KEY" -o attachment.pdf
```

The `part_id` comes from the `attachments[].part_id` field in the email detail response.

---

## Mailbox Operations

### List all mailboxes

```bash
curl -s "$MAILCUE_URL/api/v1/mailboxes" \
  -H "X-API-Key: $MAILCUE_API_KEY"
```

Returns: `mailboxes[].address`, `mailboxes[].display_name`, `mailboxes[].email_count`, `mailboxes[].unread_count`

### Create a mailbox (admin only)

```bash
curl -s -X POST "$MAILCUE_URL/api/v1/mailboxes" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "securepass", "display_name": "Alice Smith"}'
```

### Update display name

```bash
curl -s -X PUT "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/display-name" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "New Name"}'
```

### Update signature

```bash
curl -s -X PUT "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/signature" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"signature": "<p>Best regards,<br>Alice Smith</p>"}'
```

---

## Alias Operations (admin only)

### List aliases

```bash
curl -s "$MAILCUE_URL/api/v1/aliases" \
  -H "X-API-Key: $MAILCUE_API_KEY"
```

### Create alias

```bash
curl -s -X POST "$MAILCUE_URL/api/v1/aliases" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source_address": "info@example.com",
    "destination_address": "admin@example.com",
    "domain": "example.com",
    "is_catchall": false
  }'
```

### Delete alias

```bash
curl -s -X DELETE "$MAILCUE_URL/api/v1/aliases/{id}" \
  -H "X-API-Key: $MAILCUE_API_KEY"
```

---

## Health Check

```bash
curl -s "$MAILCUE_URL/api/v1/health"
# Returns: {"status":"ok","service":"mailcue-api"}
```

## Tips

- Always use `body_type: "html"` for rich emails; a text/plain fallback is auto-generated
- Threading requires `in_reply_to` and `references` — without these, replies appear as new conversations
- Search is scoped to the specified folder; search Sent and INBOX separately
- Emails are identified by `uid` within a mailbox — always include the mailbox address in requests
- The API key provides full access to the authenticated user's mailbox; admin keys can access all mailboxes
