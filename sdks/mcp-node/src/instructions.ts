/**
 * Server-level MCP `instructions`. The MCP client surfaces this to the model
 * during initialization, so it is the place to teach an agent how to run its
 * own mailbox well. The text adapts to whether a single mailbox is locked.
 */

import { isLocked, type McpConfig } from './config.js';

export function buildInstructions(config: McpConfig): string {
  const locked = isLocked(config);

  const scope = locked
    ? `You are operating a single mailbox: ${config.mailbox}. This is YOUR inbox.
You cannot see or touch any other mailbox. Tools do not take a "mailbox"
argument — every action runs against ${config.mailbox} automatically, and
mail you send goes out from ${config.mailbox}.`
    : `This server is in multi-mailbox mode. Every tool takes a required
"mailbox" argument naming the address to act on. Call list_mailboxes first to
discover which addresses exist before reading or sending.`;

  return `MailCue MCP — an email mailbox you operate directly.

MailCue is a full email server (Postfix + Dovecot + IMAP/SMTP behind a REST
API). Through this server you can read, search, triage, send, reply to, and
delete real email, the same way a person uses an inbox client.

# Scope
${scope}

# Tools
- list_emails    Browse a folder (default INBOX), newest first. Returns
                 summaries with a "uid" for each message.
- get_email      Fetch one full message by uid: bodies, headers, attachment
                 list. Read this before replying or acting on a message.
- search_emails  Full-text search across a folder (sender, subject, body).
- send_email     Send a new message. Provide "text" for plain or "html" for
                 rich; you may pass both.
- reply_email    Reply to a message by uid. Threading headers (In-Reply-To,
                 References), the "Re:" subject, and the recipient are filled
                 in for you. Just pass the uid and your reply body.
- delete_email   Permanently delete a message by uid. There is no undo.${
    locked ? '' : '\n- list_mailboxes Discover the mailboxes you can act on.'
  }
- mailbox_stats  Per-folder counts (total / unread) for a mailbox.

# How to work
1. To answer "what's in my inbox" or "any new mail", call list_emails (or
   mailbox_stats for just counts). uids come from these listings.
2. uids are scoped to a (mailbox, folder) pair. Use the same folder you listed
   from when calling get_email / reply_email / delete_email.
3. Always get_email before you reply or delete, so you act on the real content
   rather than the short preview.
4. Prefer reply_email over send_email when responding to an existing thread —
   it preserves threading so the conversation stays intact.
5. delete_email is irreversible. Only delete when explicitly asked, or when the
   task clearly calls for it.
6. Bodies may be truncated in tool output; re-fetch with get_email for the full
   text when you need it.`;
}
