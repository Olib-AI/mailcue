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
argument. Every action runs against ${config.mailbox} automatically, and
mail you send goes out from ${config.mailbox}.`
    : `This server is in multi-mailbox mode. Every tool takes a required
"mailbox" argument naming the address to act on. Call list_mailboxes first to
discover which addresses exist before reading or sending.`;

  return `MailCue MCP: an email mailbox you operate directly.

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
- score_email_deliverability
                 Score one message and return technical evidence, category
                 results, and prioritized fixes. Use it for delivery testing.
- run_email_deliverability_checks
                 Run explicit DNS, link, visual, placement, client-preview, or
                 advisory AI checks. Check capabilities first because external
                 services may be disabled or not configured.
- get_deliverability_capabilities
                 Discover which extended deliverability checks are available.
- list_deliverability_reports / compare_deliverability_reports
                 Inspect versioned history and regressions.
- list_deliverability_runs
                 Reload persisted extended evidence for one report.
- get_deliverability_artifact
                 View a protected screenshot or attention image from run evidence.
- create_deliverability_policy / evaluate_deliverability_policy
                 Define and evaluate reproducible CI gates.
- list_deliverability_alerts
                 Inspect persistent policy and scheduled-run failures.
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
- validate_email Validate one address: structure, DNS, mailbox SMTP acceptance,
                 disposable status, catch-all risk, the receiving provider, and
                 the local-part and domain signals behind the score.
- validate_email_batch Validate a whole list at once. Prefer this over looping
                 validate_email: addresses at a shared domain reveal that
                 domain's naming convention and any generated name variants.
                 Pass targetBounceRate to get the largest subset whose blended
                 bounce rate stays under a ceiling.
- get_validation_calibration How well past scores matched real outcomes.
- record_validation_feedback Record a real delivery or bounce outcome so
                 future catch-all risk estimates improve.
- ingest_bounce  Parse a raw bounce message and record the outcomes it carries.
- list_suppressed_domains Domains paused after too many measured hard bounces.
- create_send_canary / get_send_canary / list_send_canaries /
  decide_send_canary / cancel_send_canary
                 Stage a send: a sample goes first, the bounce window is
                 watched, and the rest is released only if the sample survived.

# How to work
1. To answer "what's in my inbox" or "any new mail", call list_emails (or
   mailbox_stats for just counts). uids come from these listings.
2. uids are scoped to a (mailbox, folder) pair. Use the same folder you listed
   from when calling get_email, score_email_deliverability, reply_email, or
   delete_email.
3. Always get_email before you reply or delete, so you act on the real content
   rather than the short preview.
4. Prefer reply_email over send_email when responding to an existing thread.
   It preserves threading so the conversation stays intact.
5. delete_email is irreversible. Only delete when explicitly asked, or when the
   task clearly calls for it.
6. Bodies may be truncated in tool output; re-fetch with get_email for the full
   text when you need it.
7. Validate addresses before sending. Treat deliverable=null and catch-all
   results as probabilistic; use catch_all_risk.recommended_action when present.
8. A catch-all domain accepts every recipient at RCPT time, so no probe can
   tell whether the mailbox exists. Judge those on riskScore rather than on a
   yes or no, and remember that what matters is the blended bounce rate of the
   whole send, not any single address.
9. For a bulk send to catch-all domains, use create_send_canary rather than
   send_email. A message cannot be recalled once it leaves the MTA, so the only
   protection is committing a small sample first.`;

}
