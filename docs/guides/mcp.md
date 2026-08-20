# MCP server

MailCue ships an official [Model Context Protocol](https://modelcontextprotocol.io) server, `mailcue-mcp`, that gives an AI agent its own mailbox.

The agent reads, searches, sends, replies to, and deletes email directly over MCP, managing an inbox the way a person uses a mail client. It is built on the `mailcue` Node SDK and talks to any MailCue server over the REST API.

## Add to Claude Code

```bash
claude mcp add mailcue \
  --env MAILCUE_BASE_URL=https://mail.example.com \
  --env MAILCUE_API_KEY=mc_your_api_key \
  -- npx -y mailcue-mcp@latest
```

## Other MCP clients (JSON)

```json
{
  "mcpServers": {
    "mailcue": {
      "command": "npx",
      "args": ["-y", "mailcue-mcp@latest"],
      "env": {
        "MAILCUE_BASE_URL": "https://mail.example.com",
        "MAILCUE_API_KEY": "mc_your_api_key"
      }
    }
  }
}
```

Generate an API key from the web UI **Profile** page (or `POST /api/v1/auth/api-keys`). The web UI also has a ready-to-copy config under **Developer Tools > MCP**, with `MAILCUE_BASE_URL` pre-filled for your server.

## Configuration

| Variable               | Required | Default                 | Description |
|------------------------|----------|-------------------------|-------------|
| `MAILCUE_API_KEY`      | yes\*    | (none)                  | MailCue `X-API-Key` (`mc_...`). |
| `MAILCUE_BEARER_TOKEN` | yes\*    | (none)                  | JWT alternative to the API key. |
| `MAILCUE_BASE_URL`     | no       | `http://localhost:8088` | Your MailCue server URL. |
| `MAILCUE_MAILBOX`      | no       | (none)                  | Lock the agent to a single mailbox. |

\* Provide **either** `MAILCUE_API_KEY` (preferred) or `MAILCUE_BEARER_TOKEN`.

**Single-mailbox lock:** when `MAILCUE_MAILBOX` is set, the server removes the `mailbox` argument from every tool, forces sends to that address, and hides mailbox discovery, so the agent owns exactly one inbox and cannot reach any other. Leave it unset for a multi-mailbox operator agent.

## Tools

The deliverability tools are `score_email_deliverability`,
`run_email_deliverability_checks`, `get_deliverability_capabilities`,
`list_deliverability_reports`, `compare_deliverability_reports`,
`list_deliverability_runs`,
`get_deliverability_artifact`,
`create_deliverability_policy`, `evaluate_deliverability_policy`, and
`list_deliverability_alerts`. Extended runs can request DNS, reputation, links,
local visuals, seed placement, client previews, or advisory AI analysis. The
tool reports disabled or unconfigured capabilities instead of inventing a
result.

Mailbox tools include `list_emails`, `search_emails`, `get_email`, `send_email`,
`reply_email`, `delete_email`, and `mailbox_stats`, plus `list_mailboxes` when
not locked. The server also exposes MCP `instructions` that orient the agent on
safe mailbox and deliverability workflows.

Address validation is covered by `validate_email` for one address and
`validate_email_batch` for a list. Prefer the batch tool: addresses at a shared
domain reveal that domain's naming convention and any generated name variants,
which a single lookup cannot see, and passing `targetBounceRate` returns the
largest subset whose blended expected bounce rate stays under that ceiling.
`get_validation_calibration` reports whether past scores matched reality.

Outcomes feed back through `record_validation_feedback` for a single result and
`ingest_bounce` for a raw notification. `list_suppressed_domains` shows domains
paused after too many measured hard bounces.

For a bulk send to catch-all domains, `create_send_canary` is safer than
`send_email`. A message cannot be recalled once it leaves the MTA, so a sample
goes out first and the rest is released only if the sample survived.
`get_send_canary`, `list_send_canaries`, `decide_send_canary`, and
`cancel_send_canary` drive the rest of that flow.

For full details on the tools and the SDK, see [the MCP SDK](../../sdks/mcp-node/README.md).

See the main [README](../../README.md) for the rest of the documentation.
