---
name: mailcue
description: "MailCue email server operations: send, receive, reply, forward, delete, search emails, manage mailboxes and aliases via REST API. Use when sending/reading/replying to emails, searching mailbox, managing aliases, or checking email status."
metadata: {"openclaw": {"emoji": "📧", "requires": {"env": ["MAILCUE_URL", "MAILCUE_API_KEY"]}, "primaryEnv": "MAILCUE_API_KEY"}}
---

# MailCue Email Skill

Interact with a [MailCue](https://github.com/Olib-AI/mailcue) email server via its REST API. MailCue is an open-source email server that can run as both a testing tool and a production email provider.

## When to Use

- Sending emails (with display name, CC, BCC, HTML body)
- Checking inbox for new or unread emails
- Reading a specific email's content and attachments
- Replying to or forwarding emails with proper threading
- Searching emails by subject, sender, or body
- Deleting emails or marking as read/unread
- Managing mailboxes and email aliases

## When NOT to Use

- Server setup, DNS configuration, or TLS management → use the MailCue admin UI
- Direct IMAP/POP3 client access → use a mail client
- Bulk email marketing → MailCue is not a marketing platform

## Setup

Set these environment variables:

```bash
export MAILCUE_URL="https://mail.yourdomain.com"   # Your MailCue server URL
export MAILCUE_API_KEY="mc_..."                      # API key from Profile > API Keys
```

**Tip:** If your MailCue instance is running, you can download a pre-configured skill with your server URL baked in:

```bash
curl -o SKILL.md $MAILCUE_URL/api/v1/integrations/openclaw/skill
```

### Creating an API Key

```bash
TOKEN=$(curl -s -X POST $MAILCUE_URL/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"yourpassword"}' | jq -r .access_token)

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

---

## Send an email

```bash
curl -s -X POST "$MAILCUE_URL/api/v1/emails/send" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "from_address": "user@yourdomain.com",
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
- `from_address` (required) — Sender email
- `from_name` (optional) — Display name in From header
- `to_addresses` (required) — Recipient array
- `cc_addresses`, `bcc_addresses` (optional) — CC/BCC arrays
- `subject` (required) — Subject line
- `body` (required) — Email content
- `body_type` — `"html"` or `"plain"` (default: `"plain"`)
- `in_reply_to` (optional) — Message-ID for threading replies
- `references` (optional) — Array of ancestor Message-IDs for threading

## Reply to an email

Read the original email first, then send with threading headers:

```bash
# 1. Get original email
ORIGINAL=$(curl -s "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails/{uid}" \
  -H "X-API-Key: $MAILCUE_API_KEY")

# 2. Send reply with threading
curl -s -X POST "$MAILCUE_URL/api/v1/emails/send" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "from_address": "user@yourdomain.com",
    "to_addresses": ["original-sender@example.com"],
    "subject": "Re: Original Subject",
    "body": "<p>Reply content</p>",
    "body_type": "html",
    "in_reply_to": "<message-id-from-original>",
    "references": ["<message-id-from-original>"]
  }'
```

Threading rules:
- `in_reply_to` — Message-ID of the email being replied to
- `references` — Existing References chain + parent's Message-ID
- Prefix subject with `Re: ` for replies, `Fwd: ` for forwards

## List emails

```bash
curl -s "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails?folder=INBOX&page_size=20" \
  -H "X-API-Key: $MAILCUE_API_KEY"
```

Parameters: `folder` (INBOX/Sent/Trash/Spam), `search`, `page`, `page_size`

## Read an email

```bash
curl -s "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails/{uid}" \
  -H "X-API-Key: $MAILCUE_API_KEY"
```

Returns: `html_body`, `text_body`, `from_name`, `from_address`, `to_addresses`, `subject`, `date`, `attachments[]`, `message_id`, `raw_headers`

## Delete an email

```bash
curl -s -X DELETE "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails/{uid}" \
  -H "X-API-Key: $MAILCUE_API_KEY"
```

First delete moves to Trash. Deleting from Trash permanently removes it.

## Mark as read / unread

```bash
curl -s -X PATCH "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails/{uid}/flags" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"seen": true}'
```

## Search emails

```bash
curl -s "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails?search=meeting" \
  -H "X-API-Key: $MAILCUE_API_KEY"
```

## List mailboxes

```bash
curl -s "$MAILCUE_URL/api/v1/mailboxes" \
  -H "X-API-Key: $MAILCUE_API_KEY"
```

## Manage aliases (admin)

```bash
# List
curl -s "$MAILCUE_URL/api/v1/aliases" -H "X-API-Key: $MAILCUE_API_KEY"

# Create
curl -s -X POST "$MAILCUE_URL/api/v1/aliases" \
  -H "X-API-Key: $MAILCUE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source_address": "info@yourdomain.com", "destination_address": "admin@yourdomain.com", "domain": "yourdomain.com"}'

# Delete
curl -s -X DELETE "$MAILCUE_URL/api/v1/aliases/{id}" -H "X-API-Key: $MAILCUE_API_KEY"
```

## Download attachment

```bash
curl -s "$MAILCUE_URL/api/v1/mailboxes/{mailbox}/emails/{uid}/attachments/{part_id}" \
  -H "X-API-Key: $MAILCUE_API_KEY" -o file.pdf
```

## Health check

```bash
curl -s "$MAILCUE_URL/api/v1/health"
```

## Tips

- Use `body_type: "html"` for rich emails — a text/plain fallback is auto-generated
- Threading requires `in_reply_to` and `references` — without these, replies appear as new conversations
- Emails are identified by `uid` within a mailbox
- Search is scoped to the specified folder
- Admin API keys can access all mailboxes; regular keys access only the owner's
- For a pre-configured skill with your server URL, download from: `$MAILCUE_URL/api/v1/integrations/openclaw/skill`
