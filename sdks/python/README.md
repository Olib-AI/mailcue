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
    from_name="Acme Support",
    to=["user@example.com"],
    subject="Welcome",
    html="<h1>Hi there</h1>",
)
print(result.message_id)
```

`from_name` is the display name recipients see. Leave it out and the server
falls back to the display name set on the mailbox; if that is unset too, the
message goes out as a bare address and mail clients show
`hello@example.com` instead of a name.

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

## Waiting for an email (CI)

`wait_for` polls a mailbox until matching messages arrive, or raises
`mailcue.TimeoutError` after `timeout` seconds. Filters (`subject`,
`from_address`, `to_address`) are case-insensitive substrings on top of the
server-side `search`.

```python
found = client.emails.wait_for(
    mailbox="user@test.com",
    subject="Welcome",
    timeout=10,
)
assert len(found) == 1
```

## Email validation and catch-all risk

```python
result = client.emails.validate("person@example.com")
print(result.provider.name, result.mailbox.selective_recipient_validation)
if result.catch_all_risk:
    print(result.catch_all_risk.score, result.catch_all_risk.recommended_action)
    for item in result.catch_all_risk.contributions:
        print(item.label, item.delta, item.detail)
```

A catch-all domain accepts every recipient at RCPT time, so no probe can prove
that a mailbox exists. `catch_all_risk.score` is therefore a hard-bounce
probability rather than a verdict: it starts from the receiving provider's
rate, is refined by outcomes seen at that provider and domain, and is then
adjusted for the local part and passive domain signals.

Validate a list together rather than one address at a time. Addresses sharing a
domain reveal that domain's naming convention and any generated name variants,
and `target_bounce_rate` returns the largest subset whose blended expected
bounce rate stays under the ceiling receivers actually judge you on.

```python
batch = client.emails.validate_batch(addresses, target_bounce_rate=0.015)
print(batch.summary.catch_all, batch.selection.projected_bounce_rate)
send_to = batch.selection.included
```

Feed outcomes back so the estimates improve. A raw bounce can be handed over
whole instead of being summarised by hand.

```python
client.emails.record_validation_feedback(
    "person@example.com", "hard_bounce", smtp_code=550, enhanced_status="5.1.1"
)
client.emails.ingest_bounce(raw_dsn_message)

# Check that the published probabilities held up.
report = client.emails.validation_calibration(days=90)
print(report.brier_score, report.observed_rate)
```

## Staged sending

A message cannot be recalled once it leaves the MTA, so the only way to bound
exposure on a catch-all domain is to not commit the whole batch at once. A
staged send delivers a small sample first, watches the bounce window, and
releases the rest only if the sample survived.

```python
canary = client.emails.create_send_canary(
    recipients=addresses,
    from_address="hello@example.com",
    subject="Quarterly update",
    body="...",
    sample_size=2,
    hold_minutes=15,
)
state = client.emails.get_send_canary(canary.id)
print(state.status, state.decision_reason)
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
    api_key="mc_xxx",  # or bearer_token="eyJ..."
    base_url="https://mail.example.com",  # default: http://localhost:8088
    timeout=30.0,  # seconds
    max_retries=3,  # 502/503/504 + network errors
    verify=True,  # set False for self-signed dev TLS
)
```

You can also inject your own `httpx.Client` / `httpx.AsyncClient` via
`http_client=` for advanced cases (custom transports, proxies, mTLS).

## Resources

| Resource | Methods |
|----------|---------|
| `client.emails` | `send`, `list`, `get`, `get_raw`, `get_attachment`, `delete`, `inject`, `bulk_inject`, `validate`, `validate_batch`, `record_validation_feedback`, `ingest_bounce`, `validation_calibration`, `suppressed_domains`, `create_send_canary`, `list_send_canaries`, `get_send_canary`, `decide_send_canary`, `cancel_send_canary` |
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
