# mailcue-mcp

<p align="center">
  <img src="https://raw.githubusercontent.com/Olib-AI/mailcue/main/logo.svg" alt="MailCue" width="280" />
</p>

A [Model Context Protocol](https://modelcontextprotocol.io) server for
[MailCue](https://github.com/Olib-AI/mailcue) — the open-source email testing and
production server. It gives an AI agent **its own mailbox**: the agent can read,
search, triage, send, reply to, and delete email directly, managing an inbox the
way a person uses a mail client.

Built on the official [`mailcue`](https://www.npmjs.com/package/mailcue) Node SDK
and the MCP TypeScript SDK. Talks to any MailCue server over its REST API.

## Why

MailCue already exposes a full mail stack (Postfix + Dovecot + IMAP/SMTP) behind
one API. This server turns that API into MCP tools so an agent can own and run a
mailbox end-to-end — answering mail, keeping threads tidy, clearing the inbox —
better and faster than a human babysitting it.

## Install / run

Requires Node.js 18+ and a running MailCue server with an API key.

```bash
npx mailcue-mcp
```

The server speaks MCP over **stdio**, so you normally launch it from an MCP
client's config rather than by hand.

## Configuration

All configuration is via environment variables:

| Variable               | Required | Default                  | Description |
| ---------------------- | -------- | ------------------------ | ----------- |
| `MAILCUE_API_KEY`      | yes\*    | —                        | MailCue `X-API-Key` (`mc_...`). |
| `MAILCUE_BEARER_TOKEN` | yes\*    | —                        | JWT alternative to the API key. |
| `MAILCUE_BASE_URL`     | no       | `http://localhost:8088`  | Your MailCue server URL. |
| `MAILCUE_MAILBOX`      | no       | —                        | Lock the agent to a single mailbox (see below). |

\* Provide **either** `MAILCUE_API_KEY` (preferred) or `MAILCUE_BEARER_TOKEN`.

### Single-mailbox lock

When `MAILCUE_MAILBOX` is set, the server runs in **locked** mode:

- Every tool operates only on that mailbox. The `mailbox` argument is removed
  from all tool schemas, so the agent **cannot read or touch any other mailbox**.
- `send_email` and `reply_email` always send **from** the locked address.
- The `list_mailboxes` discovery tool is not registered.

This is the recommended way to give one agent one inbox it fully owns. Leave
`MAILCUE_MAILBOX` unset for an operator/admin agent that works across mailboxes;
in that mode every tool takes a required `mailbox` argument and `list_mailboxes`
is available for discovery.

## Using with an MCP client

### Claude Desktop / Claude Code (`mcp.json`)

```json
{
  "mcpServers": {
    "mailcue": {
      "command": "npx",
      "args": ["-y", "mailcue-mcp"],
      "env": {
        "MAILCUE_BASE_URL": "http://localhost:8088",
        "MAILCUE_API_KEY": "mc_your_api_key",
        "MAILCUE_MAILBOX": "agent@mailcue.local"
      }
    }
  }
}
```

Drop `MAILCUE_MAILBOX` to let the agent work across every mailbox on the server.

## Tools

| Tool             | Purpose | Locked-mode note |
| ---------------- | ------- | ---------------- |
| `list_emails`    | List a folder's emails (newest first); returns uids. | no `mailbox` arg |
| `search_emails`  | Full-text search a folder. | no `mailbox` arg |
| `get_email`      | Fetch one full email by uid (body, headers, attachments). | no `mailbox` arg |
| `send_email`     | Send a new email. | sends from the locked address; no `from` arg |
| `reply_email`    | Reply by uid; threading + `Re:` subject set automatically. | replies from the locked address |
| `delete_email`   | Permanently delete an email by uid. | no `mailbox` arg |
| `mailbox_stats`  | Per-folder total / unread counts. | no `mailbox` arg |
| `validate_email` | Validate structure, DNS status, mailbox SMTP availability, and disposable status. | independent of mailbox |
| `list_mailboxes` | Discover available mailboxes. | **not available when locked** |

uids are scoped to a `(mailbox, folder)` pair — read and act using the same
folder you listed from. HTML bodies are converted to readable text and long
bodies are truncated; re-fetch with `get_email` for the full message.

### Built-in agent instructions

The server ships MCP `instructions` (surfaced to the model at initialization)
that explain the mailbox scope, when to use each tool, and safe-handling rules
(e.g. read before replying or deleting, prefer `reply_email` to keep threads
intact, deletes are irreversible). The text adapts to locked vs. multi-mailbox
mode, so the agent is oriented without any extra prompting on your side.

## Development

```bash
npm install
npm run typecheck
npm run lint
npm run build      # bundles to dist/index.js (stdio entrypoint)
```

## License

MIT — see `LICENSE`. Part of [MailCue](https://github.com/Olib-AI/mailcue) by
[Olib AI](https://www.olib.ai).
