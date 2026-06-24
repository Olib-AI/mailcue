# Provider sandbox and HTTP bin

How MailCue captures outbound API traffic for local testing, and the built-in HTTP request inspector.

## Sandbox Providers

Beyond email, MailCue ships a configurable HTTP sandbox layer that captures outbound API traffic from your application for local testing. It exposes wire-protocol-identical endpoints for a range of messaging and telephony channels, letting you point your existing SDK at MailCue's base URL and run full end-to-end validation without touching external services.

### Supported channels

| Channel            | Coverage |
|--------------------|----------|
| **Chat messaging** | Inbound and outbound message capture with signed webhooks |
| **SMS / MMS**      | Send, receive, and delivery-status callbacks |
| **Voice**          | Call lifecycle (initiated → ringing → answered → in-progress → completed) driven by a shared verb-execution state machine |
| **Number search**  | Available-number lookup and purchase |
| **Number porting** | Port-in order lifecycle (coverage varies per configured provider) |
| **A2P 10DLC**      | Brand and campaign registration (coverage varies per configured provider) |

All sandbox routes live under `/sandbox/<provider>/<api-version>/...`. Each configured provider keeps its own wire-format (URL shape, auth mechanism, request/response schemas, and webhook payload signatures) so your production SDK can talk to the sandbox unchanged.

### Capabilities

- Create sandbox instances via the UI or API (`/api/v1/sandbox/providers`)
- Simulate inbound traffic (upstream → your app) and send outbound traffic (your app → upstream, which fires webhooks back)
- Configure webhook endpoints with automatic retry and exponential backoff (up to 3 attempts) via the `SandboxWebhookDelivery` queue
- Native authentication per provider (HTTP Basic, Bearer JWT, Bearer token, etc.) matching the upstream's real scheme
- Ed25519-signed webhooks for providers that use them, with public-key retrieval endpoints
- Call verbs normalised into a common intermediate representation so the same state machine drives every voice dialect

Fetch the live capability matrix for every configured sandbox at `GET /sandbox/providers/capabilities`. Features not exposed by a given upstream return `provider_unsupported`, matching production behaviour.

### Call lifecycle timings

All timings are configurable via environment variables (milliseconds):

| Variable                               | Default | Controls                              |
|----------------------------------------|---------|---------------------------------------|
| `MAILCUE_SANDBOX_VOICE_RING_MS`        | 100     | Delay from `initiated` to `ringing`   |
| `MAILCUE_SANDBOX_VOICE_ANSWER_MS`      | 100     | Delay from `ringing` to `answered`    |
| `MAILCUE_SANDBOX_VOICE_ACTION_MS`      | 50      | Delay between each IR action          |
| `MAILCUE_SANDBOX_VOICE_COMPLETE_MS`    | 50      | Delay from last action to `completed` |

Known limitation: the sandbox drives call **lifecycle and verb execution** only. No actual audio is streamed. Recording verbs post a synthetic recording identifier back to the action URL.

### TLS / hostname pinning

Sandbox routes inherit the same TLS stack as the rest of the MailCue HTTP API. If your SDK performs hostname pinning, add aliases in your DNS or `/etc/hosts` pointing at the MailCue host, then download the MailCue CA via `GET /api/v1/system/certificate/download` and install it in your client's trust store (see [Email clients and TLS trust](clients.md)).

## HTTP Bin

A built-in request inspector at `/http-bin` in the UI. Create bins, point webhooks or any HTTP client at the bin URL, and inspect every captured request (method, headers, query params, and body) in real time. Useful for verifying webhook payloads without leaving MailCue.
