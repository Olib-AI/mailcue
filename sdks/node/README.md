# mailcue

Official Node.js / TypeScript SDK for [MailCue](https://github.com/Olib-AI/mailcue) — the open-source email testing and production server.

Build against MailCue locally in test mode, then point at your production deployment by changing one option. No code changes required.

## Install

```bash
npm install mailcue
```

Requires Node.js 18 or newer (for native `fetch`). No runtime dependencies.

## Quick start

```ts
import { Mailcue } from 'mailcue';

const mc = new Mailcue({
  apiKey: 'mc_your_api_key',
  baseUrl: 'http://localhost:8088',
});

const { messageId } = await mc.emails.send({
  from: 'hello@example.com',
  to: ['user@example.com'],
  subject: 'Welcome',
  html: '<h1>Hi</h1>',
});

console.log('queued', messageId);
```

## Authentication

Either pass an API key (preferred for server-to-server) or a JWT bearer token:

```ts
const mc = new Mailcue({ apiKey: 'mc_...' });
// or
const mc = new Mailcue({ bearerToken: '...' });
```

## Sending mail

```ts
import { readFileSync } from 'node:fs';

await mc.emails.send({
  from: 'noreply@example.com',
  fromName: 'Example',
  to: ['user@example.com'],
  cc: ['ops@example.com'],
  replyTo: 'support@example.com',
  subject: 'Your invoice',
  html: '<p>Thanks for your order.</p>',
  attachments: [
    {
      filename: 'invoice.pdf',
      contentType: 'application/pdf',
      content: readFileSync('./invoice.pdf'),
    },
  ],
});
```

`content` accepts `Buffer`, `Uint8Array`, or `string` (UTF-8). The SDK base64-encodes it for you.

## Reading mail

```ts
const inbox = await mc.emails.list({
  mailbox: 'user@example.com',
  page: 1,
  pageSize: 50,
});

for (const summary of inbox.emails) {
  const detail = await mc.emails.get(summary.uid, { mailbox: summary.mailbox });
  console.log(detail.subject, detail.textBody);
}

await mc.emails.delete(inbox.emails[0].uid, { mailbox: 'user@example.com' });
```

## Mailboxes, domains, aliases, GPG, API keys, system

```ts
await mc.mailboxes.create({ username: 'alice', password: 'secret', domain: 'example.com' });
const stats = await mc.mailboxes.stats('alice@example.com');

await mc.domains.create({ name: 'example.com' });
const dns = await mc.domains.verifyDns('example.com');

await mc.aliases.create({ sourceAddress: 'sales@example.com', destinationAddress: 'team@example.com' });

const key = await mc.gpg.generate({ mailboxAddress: 'alice@example.com' });
const armored = await mc.gpg.exportPublic('alice@example.com');

const created = await mc.apiKeys.create({ name: 'ci' });
console.log('save this once', created.key);

const health = await mc.system.health();
```

## Streaming events (SSE)

```ts
for await (const event of mc.events.stream()) {
  if (event.type === 'email.received') {
    console.log('new mail in', event.data);
  }
}
```

Auto-reconnects with exponential backoff on disconnect. Pass an `AbortSignal` to cancel:

```ts
const ctrl = new AbortController();
setTimeout(() => ctrl.abort(), 60_000);

for await (const event of mc.events.stream({ signal: ctrl.signal })) {
  // ...
}
```

## Errors

All errors extend `MailcueError`. Use `instanceof` to handle them granularly:

```ts
import { Mailcue, RateLimitError, ValidationError, AuthenticationError } from 'mailcue';

try {
  await mc.emails.send({ /* ... */ });
} catch (err) {
  if (err instanceof RateLimitError) {
    console.warn('rate limited, retry after', err.retryAfter, 'seconds');
  } else if (err instanceof ValidationError) {
    console.warn('bad input', err.body);
  } else if (err instanceof AuthenticationError) {
    console.error('check your api key');
  } else {
    throw err;
  }
}
```

Exported error classes: `MailcueError`, `AuthenticationError`, `AuthorizationError`, `NotFoundError`, `ConflictError`, `ValidationError`, `RateLimitError`, `ServerError`, `NetworkError`, `TimeoutError`.

Each carries `status`, `code`, `requestId` (when available), and the parsed response `body`.

## Pointing at production

The `baseUrl` is the only thing that changes between environments:

```ts
const mc = new Mailcue({
  apiKey: process.env.MAILCUE_API_KEY!,
  baseUrl: process.env.MAILCUE_URL ?? 'http://localhost:8088',
});
```

## Configuration

| Option        | Default                  | Notes                                          |
| ------------- | ------------------------ | ---------------------------------------------- |
| `apiKey`      | —                        | Either this or `bearerToken` is required.      |
| `bearerToken` | —                        | JWT alternative to `apiKey`.                   |
| `baseUrl`     | `http://localhost:8088`  | Your MailCue server.                           |
| `timeout`     | `30000`                  | Per-request timeout in ms.                     |
| `maxRetries`  | `3`                      | Retries on `502 / 503 / 504` and network errors. |
| `fetch`       | `globalThis.fetch`       | Inject a custom fetch (testing, proxies).      |
| `userAgent`   | `mailcue-node/<version>` | Override the User-Agent header.                |

## License

MIT — see `LICENSE`. Source: <https://github.com/Olib-AI/mailcue>
