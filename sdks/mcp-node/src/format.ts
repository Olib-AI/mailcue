/**
 * Shape MailCue SDK responses into compact, token-efficient text for the model.
 * Tools return readable JSON rather than dumping raw HTML bodies.
 */

import type {
  EmailDetail,
  EmailListResponse,
  EmailSummary,
  MailboxListResponse,
  MailboxStats,
} from 'mailcue';

const MAX_BODY_CHARS = 8000;

/** Best-effort HTML -> text so the model reads prose, not markup. */
export function htmlToText(html: string): string {
  return html
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<\/(p|div|tr|li|h[1-6])>/gi, '\n')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function truncate(text: string): string {
  if (text.length <= MAX_BODY_CHARS) return text;
  return `${text.slice(0, MAX_BODY_CHARS)}\n\n[...truncated ${text.length - MAX_BODY_CHARS} chars. Use get_email with the uid for the full message.]`;
}

function summaryView(e: EmailSummary): Record<string, unknown> {
  return {
    uid: e.uid,
    from: e.fromAddress,
    to: e.toAddresses,
    subject: e.subject,
    date: e.date,
    unread: !e.isRead,
    hasAttachments: e.hasAttachments,
    preview: e.preview,
  };
}

export function formatList(res: EmailListResponse, folder: string): string {
  const view = {
    folder,
    total: res.total,
    page: res.page,
    pageSize: res.pageSize,
    hasMore: res.hasMore,
    returned: res.emails.length,
    emails: res.emails.map(summaryView),
  };
  return JSON.stringify(view, null, 2);
}

export function formatEmail(e: EmailDetail): string {
  const bestBody = e.textBody ?? (e.htmlBody ? htmlToText(e.htmlBody) : '');
  const view = {
    uid: e.uid,
    mailbox: e.mailbox,
    messageId: e.messageId,
    from: e.fromAddress,
    to: e.toAddresses,
    cc: e.ccAddresses,
    subject: e.subject,
    date: e.date,
    unread: !e.isRead,
    isSigned: e.isSigned,
    isEncrypted: e.isEncrypted,
    attachments: e.attachments.map((a) => ({
      partId: a.partId,
      filename: a.filename,
      contentType: a.contentType,
      size: a.size,
    })),
    body: truncate(bestBody),
  };
  return JSON.stringify(view, null, 2);
}

export function formatStats(s: MailboxStats): string {
  return JSON.stringify(
    {
      address: s.address,
      totalEmails: s.totalEmails,
      unreadEmails: s.unreadEmails,
      totalSizeBytes: s.totalSizeBytes,
      folders: s.folders.map((f) => ({
        name: f.name,
        messages: f.messageCount,
        unseen: f.unseenCount,
      })),
    },
    null,
    2,
  );
}

export function formatMailboxes(res: MailboxListResponse): string {
  return JSON.stringify(
    {
      total: res.total,
      mailboxes: res.mailboxes.map((m) => ({
        address: m.address,
        displayName: m.displayName,
        emailCount: m.emailCount,
        unreadCount: m.unreadCount,
      })),
    },
    null,
    2,
  );
}
