# MailCue Python SDK

Official Python client for [MailCue](https://github.com/Olib-AI/mailcue) — the
open-source email testing and production server (Postfix + Dovecot + FastAPI +
React) packaged as one Docker container.

The SDK is the same in dev and prod: point it at `http://localhost:8088` while
you build, then swap `base_url` to your production MailCue deployment when you
ship.

## Install

```bash
pip install mailcue
```

Requires Python 3.9+.

## Quick start: send an email

```python
from mailcue import Mailcue

client = Mailcue(api_key="mc_xxx")  # base_url defaults to http://localhost:8088

result = client.emails.send(
    from_="hello@example.com",
    to=["user@example.com"],
    subject="Welcome",
    html="<h1>Hi there</h1>",
)
print(result.message_id)
```

Need async? Use `AsyncMailcue` — same surface, all methods become coroutines:

```python
import asyncio
from mailcue import AsyncMailcue

async def main() -> None:
    async with AsyncMailcue(api_key="mc_xxx") as client:
        await client.emails.send(
            from_="hello@example.com",
            to=["user@example.com"],
            subject="Welcome",
            html="<h1>Hi there</h1>",
        )

asyncio.run(main())
```

## Listing an inbox

```python
inbox = client.emails.list(mailbox="user@example.com", page_size=20)
for email in inbox.emails:
    print(email.uid, email.subject, email.from_address)

detail = client.emails.get(inbox.emails[0].uid, mailbox="user@example.com")
print(detail.text_body)
```

## Attachments

`attachments` accepts raw `bytes`, `str`, or a `pathlib.Path`. The SDK
base64-encodes the content for you.

```python
from pathlib import Path

client.emails.send(
    from_="hello@example.com",
    to=["user@example.com"],
    subject="Invoice",
    html="<p>See attached.</p>",
    attachments=[
        {
            "filename": "invoice.pdf",
            "content_type": "application/pdf",
            "content": Path("./invoice.pdf"),
        }
    ],
)
```

## Real-time events (SSE)

```python
for event in client.events.stream():
    print(event.event_type, event.data)
```

The async version:

```python
async with AsyncMailcue(api_key="mc_xxx") as client:
    async for event in client.events.stream():
        print(event.event_type, event.data)
```

The SSE client auto-reconnects with exponential backoff if the connection
drops.

## Error handling

```python
from mailcue import (
    Mailcue,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)

client = Mailcue(api_key="mc_xxx")

try:
    client.emails.get("not-a-real-uid", mailbox="user@example.com")
except NotFoundError as exc:
    print("missing:", exc)
except RateLimitError as exc:
    print(f"slow down; retry after {exc.retry_after}s")
except AuthenticationError:
    print("bad API key")
except ValidationError as exc:
    print("server rejected the request:", exc.detail)
```

## Configuration

```python
client = Mailcue(
    api_key="mc_xxx",                        # or bearer_token="eyJ..."
    base_url="https://mail.example.com",     # default: http://localhost:8088
    timeout=30.0,                            # seconds
    max_retries=3,                           # 502/503/504 + network errors
    verify=True,                             # set False for self-signed dev TLS
)
```

You can also inject your own `httpx.Client` / `httpx.AsyncClient` via
`http_client=` for advanced cases (custom transports, proxies, mTLS).

## Resources

| Resource | Methods |
|----------|---------|
| `client.emails` | `send`, `list`, `get`, `get_raw`, `get_attachment`, `delete`, `inject`, `bulk_inject` |
| `client.mailboxes` | `list`, `create`, `delete`, `stats`, `purge`, `list_emails` |
| `client.domains` | `list`, `create`, `get`, `verify_dns`, `delete` |
| `client.aliases` | `list`, `create`, `get`, `update`, `delete` |
| `client.gpg` | `list`, `generate`, `get`, `export_public`, `import_key`, `publish`, `delete` |
| `client.api_keys` | `list`, `create`, `delete` |
| `client.system` | `health`, `get_certificate`, `download_certificate`, `settings`, `tls_status` |
| `client.events` | `stream()` (SSE iterator) |

## License

MIT — see `LICENSE`.

Project home: https://github.com/Olib-AI/mailcue
