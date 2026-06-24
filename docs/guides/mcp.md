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

`list_emails`, `search_emails`, `get_email`, `send_email`, `reply_email`, `delete_email`, `mailbox_stats` (plus `list_mailboxes` when not locked). The server also exposes MCP `instructions` that orient the agent on how to triage and reply safely.

For full details on the tools and the SDK, see [the MCP SDK](../../sdks/mcp-node/README.md).

See the main [README](../../README.md) for the rest of the documentation.
