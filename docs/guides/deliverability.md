# Deliverability testing

MailCue can dedicate a normal mailbox to deliverability testing. It still receives mail through the same SMTP and IMAP stack, but message detail opens a scored report and the Deliverability command center adds history, comparisons, automation, visual results, and placement evidence.

Create a mailbox with `purpose: "deliverability"`. This does not create a second class of mail storage and does not change delivery behavior.

## Capability parity and deployment boundaries

MailCue covers the Mail-Tester and Unspam workflow while keeping infrastructure-dependent claims explicit.

| Capability | MailCue implementation |
|---|---|
| Authentication and message score | Deterministic local SPF, DKIM, DMARC, alignment, header, MIME, content, attachment, transport, and SpamAssassin analysis |
| IP, domain, and URL reputation | Opt-in public DNS with operator-selected IP and domain blocklist zones; no zone is contacted by default |
| Link health | SSRF-resistant, pinned public HTTP and HTTPS probes with no redirects |
| Accessibility | Language, image alternatives, heading order, preheader, explicit inline contrast, tap-target, CSS, and image-blocked visual evidence |
| Responsive visual checks | Network-blocked desktop, tablet, and mobile light and dark local renders |
| Attention heatmaps | Deterministic desktop, tablet, and mobile saliency estimates, clearly labeled as estimates rather than measured eye tracking |
| Real email clients | Up to 100 results per run through the configured client-preview provider; MailCue does not claim that local Chromium is Outlook or Gmail |
| Inbox placement | Exact Message-ID classification across operator-controlled, verified seed inboxes, including category, spam, missing, and unavailable states |
| AI guidance | Optional bounded HTTPS analysis provider; advisory results never alter the deterministic score |
| History and monitoring | Immutable reports, persisted extended runs, trends, baselines, regressions, recurring schedules, policies, and persistent alerts |
| Sharing and automation | JSON, CSV, and printable HTML exports, REST, Node SDK, Postman, MCP, and CI policy evaluation |

MailCue does not bundle a commercial seed network or a farm of proprietary email clients. Real-client and provider-diverse placement coverage therefore depends on infrastructure the operator controls or configures. Scheduled placement checks inspect seed messages that the campaign sender delivered; MailCue does not impersonate the original sender or silently resend campaign mail.

## What is measured

The versioned local score is deterministic and uses the original RFC 5322 message received by MailCue.

- Receiver-recorded SPF, DKIM, and DMARC results, including visible From alignment
- Header identity, Message-ID, Date, MIME, Return-Path, Reply-To, duplicates, and unsubscribe support
- Plain-text and HTML alternatives, risky language, deceptive links, hidden text, tracking pixels, preheaders, and email-client CSS risks
- Accessibility evidence for language, image alternatives, heading order, explicit inline color contrast, and explicitly sized tap targets
- Active or unsupported HTML, image-to-text balance, image alternative text, and unsafe attachment names or sizes
- TLS route evidence, origin identity, ARC presence, and local SpamAssassin score
- Structured SpamAssassin rule codes, rule scores when available, descriptions, and targeted guidance

The score model version is stored with every immutable report. Updating MailCue does not rewrite an older report with a newer model.

## Extended checks

Extended checks are explicit runs attached to a base report. They do not silently add network access to local scoring.

| Check | Source | Default |
|---|---|---|
| DNS policies | Public DNS for SPF, DKIM, DMARC, MX, BIMI, MTA-STS, and TLS-RPT | Disabled |
| Reputation | Sender IP reverse DNS, HELO/EHLO identity, HELO SPF, and operator-configured DNSBL zones | Disabled |
| Live links | Pinned public HTTP or HTTPS destinations, without redirects | Disabled |
| Visual | Local Chromium desktop, tablet, and mobile renders in light and dark modes | Disabled |
| Client previews | Configured external HTTPS provider | Not configured |
| Placement | Configured operator-controlled seed inboxes | Not configured |
| AI-assisted copy review | Configured external HTTPS provider | Not configured |

Use `GET /api/v1/deliverability/capabilities` to discover the actual deployment state. MailCue reports `available`, `disabled`, `not_configured`, or `unavailable`. It never substitutes a guessed result for a service that did not run.

## Network security

Network checks are disabled until `MAILCUE_DELIVERABILITY_NETWORK_CHECKS_ENABLED=true` is set.

Live-link and preview adapters:

- resolve destinations under a bounded timeout
- require every resolved address to be globally routable
- pin the connection to the validated address
- preserve the original TLS server name for certificate validation
- reject credentials in URLs and non-web ports
- disable redirects and environment proxy inheritance
- cap concurrency, response size, and execution time

DNS blocklists are never selected by MailCue. Configure only zones whose terms and privacy behavior you accept:

```env
MAILCUE_DELIVERABILITY_DNSBL_ZONES=["zen.example-dnsbl.net"]
MAILCUE_DELIVERABILITY_DOMAIN_DNSBL_ZONES=["multi.example-domain-list.net"]
```

The first list receives reversed-octet IPv4 or reversed-nibble IPv6 queries. The second receives visible From, receiver-verified MAIL FROM, DKIM signing, and linked-domain queries. Empty lists produce informational results and make no listing claim. MailCue accepts loopback DNSBL answers as listings, treats reserved provider error answers or unexpected addresses as query failures, and does not copy account-bearing zone names into report evidence.

Sender infrastructure checks evaluate the external identities observed for each tested message, regardless of whether any of their domains are configured in MailCue. The visible `From` domain is used for DMARC and domain-posture checks, the receiver-verified MAIL FROM domain is used for SPF with HELO as its fallback, and observed DKIM selectors are queried under their signing domains. MailCue skips its leading loopback SpamAssassin re-injection hop and uses the first public handoff recorded by its receiving MTA for the origin IP and HELO or EHLO identity. It does not walk past a private or malformed boundary into older sender-supplied route fields.

## Local visual rendering

The production image includes Chromium, but rendering remains disabled until explicitly enabled:

```env
MAILCUE_DELIVERABILITY_VISUAL_CHECKS_ENABLED=true
MAILCUE_DELIVERABILITY_CHROMIUM_PATH=chromium
MAILCUE_DELIVERABILITY_VISUAL_TIMEOUT_SECONDS=30
MAILCUE_DELIVERABILITY_ARTIFACT_MAX_BYTES=5242880
```

MailCue places a restrictive Content Security Policy before message HTML, blocks Chromium name resolution and proxy access, disables scripts, connections, forms, frames, objects, and remote media, and stores resulting PNGs as tenant-protected artifacts. When the API service runs as root, only the Chromium child is dropped to the unprivileged `nobody` account before it reads the temporary message document. Artifact URLs require the same user, API scope, and mailbox permission as the report.

MailCue also generates deterministic desktop, tablet, and mobile attention estimates from local contrast and edge saliency. They are labeled as design aids, not measured eye tracking. When a baseline report also has visual artifacts, MailCue calculates a normalized pixel difference for each matching viewport and warns on material changes.

## Real-client preview provider

Real Outlook, Gmail, Apple Mail, mobile, and legacy client screenshots require infrastructure outside the MailCue container. Configure a `generic_http_preview` provider to use a service you operate or license.

MailCue sends an explicit preview run as:

```http
POST /configured/provider/path
Content-Type: message/rfc822
Accept: application/json
Authorization: Bearer configured-write-only-secret
X-MailCue-Preview-Contract: 1
```

The request body is the original message. The provider response contract is:

```json
{
  "previews": [
    {
      "client": "Outlook 365",
      "platform": "Windows",
      "theme": "dark",
      "status": "ready",
      "description": "Rendered successfully",
      "media_type": "image/png",
      "image_base64": "..."
    }
  ]
}
```

MailCue accepts at most 100 results, only PNG or JPEG image data, and a bounded total response. It copies images into protected artifact storage and does not hotlink provider URLs. Provider secrets are encrypted at rest with a domain-separated key and are never returned by REST, SDK, MCP, or UI responses.

## AI-assisted copy review provider

The optional `generic_http_analysis` provider uses the same pinned HTTPS transport, size limits, write-only secret handling, and explicit-run behavior as client previews. The original message is sent only when a user requests `ai_analysis`.

The provider returns bounded advisory findings:

```json
{
  "summary": "The primary action could be clearer.",
  "findings": [
    {
      "severity": "suggestion",
      "title": "Clarify the call to action",
      "detail": "The action label is ambiguous.",
      "recommendation": "Use one specific action label."
    }
  ]
}
```

AI findings have no score weight and cannot modify the deterministic base report. This keeps CI gates reproducible and separates measured evidence from subjective advice.

## BYO seed inbox placement

Placement uses verified SSL IMAP accounts already configured under Email Warmup. Create a `seed_imap` provider with one to fifty account IDs and the folders to inspect.

MailCue does not send the tested message to seed accounts. Send the same campaign message to the MailCue test address and the seed addresses. A placement run searches the configured folders by the exact Message-ID and reports:

- `inbox`
- `category`, such as Promotions or Social
- `spam`
- `missing`
- `unavailable`

SSL connections are pinned to validated public addresses while preserving the IMAP hostname for certificate verification. Missing, disabled, unverified, unsafe, or unreachable accounts remain `unavailable` and are not counted as inbox results.

## History, baselines, and exports

Every report stores a SHA-256 digest of the raw message, scoring version, score, verdict, and complete JSON snapshot. Identical message bytes, folder, UID, and scoring version reuse the same report.

Select one baseline per mailbox. Comparisons show total score change, category changes, and check-level improvements or regressions. Trend data is available to the web command center and API.

Reports export as JSON, CSV, or printable HTML:

```text
GET /api/v1/deliverability/reports/{report_id}/export?format=json
GET /api/v1/deliverability/reports/{report_id}/export?format=csv
GET /api/v1/deliverability/reports/{report_id}/export?format=html
```

## CI policies, schedules, and alerts

A policy can require:

- a minimum score
- a maximum score regression from the baseline or previous report
- no checks with selected blocked statuses
- specific check IDs to pass
- specific deployment capabilities to be available

Policy evaluations are immutable per policy and report. A failed evaluation creates a persistent alert.

Schedules claim their next execution slot before accessing IMAP, preventing duplicate bursts across workers. They analyze the latest INBOX message, optionally run extended checks, optionally evaluate a policy, and create alerts for empty mailboxes, incomplete runs, or failures.

## Primary REST endpoints

```text
GET  /api/v1/mailboxes/{mailbox}/emails/{uid}/deliverability
POST /api/v1/mailboxes/{mailbox}/emails/{uid}/deliverability/runs
GET  /api/v1/deliverability/capabilities
GET  /api/v1/deliverability/reports
GET  /api/v1/deliverability/reports/{id}
GET  /api/v1/deliverability/reports/{id}/runs
PUT  /api/v1/deliverability/reports/{id}/baseline
GET  /api/v1/deliverability/reports/{id}/comparison
GET  /api/v1/deliverability/trends
GET  /api/v1/deliverability/runs/{id}
GET  /api/v1/deliverability/artifacts/{id}
GET, POST, PUT, DELETE /api/v1/deliverability/policies
GET, POST, PUT, DELETE /api/v1/deliverability/providers
GET, POST, PUT, DELETE /api/v1/deliverability/schedules
GET  /api/v1/deliverability/alerts
POST /api/v1/deliverability/alerts/{id}/acknowledge
```

The committed OpenAPI and Postman files contain exact request and response schemas.

## MCP tools

The MCP server exposes local scoring, extended runs, capability discovery, report history, comparisons, policy creation and evaluation, and alert listing. Extended runs are marked as open-world operations because they may access configured public DNS, links, seed inboxes, a preview provider, or an analysis provider.

## Honest limitations

- A high score cannot guarantee inbox placement.
- A local Chromium render is not a real email-client render.
- A seed result covers only the inboxes the operator controls and queried successfully.
- A DNSBL result covers only explicitly configured zones at that moment.
- MailCue does not claim historical sender reputation from providers that do not expose it.
- Preview quality and client coverage depend on the configured provider.
- AI-assisted findings depend on the configured provider and remain advisory.

These limitations are preserved in reports and capability responses so CI systems and AI agents can distinguish measured evidence from unavailable data.
