import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { Mailcue, MailcueError, type SendEmailParams } from 'mailcue';
import { z, type ZodRawShape } from 'zod';

import { isLocked, type McpConfig } from './config.js';
import {
  formatEmail,
  formatList,
  formatMailboxes,
  formatStats,
} from './format.js';
import { buildInstructions } from './instructions.js';

export const SERVER_VERSION = '0.1.0';

type ToolResult = {
  content: { type: 'text'; text: string }[];
  isError?: boolean;
};

/** A failure we deliberately surface to the model as tool output, not a crash. */
class ToolError extends Error {}

function text(value: string): ToolResult {
  return { content: [{ type: 'text', text: value }] };
}

function toolError(message: string): ToolResult {
  return { content: [{ type: 'text', text: message }], isError: true };
}

function describeError(err: unknown): string {
  if (err instanceof ToolError) return err.message;
  if (err instanceof MailcueError) {
    const status = err.status ? ` (HTTP ${err.status})` : '';
    return `MailCue request failed${status}: ${err.message}`;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}

const FOLDER = z
  .string()
  .optional()
  .describe('IMAP folder to act in. Defaults to INBOX.');

export function buildServer(config: McpConfig): McpServer {
  const locked = isLocked(config);

  const client = new Mailcue({
    baseUrl: config.baseUrl,
    ...(config.apiKey ? { apiKey: config.apiKey } : {}),
    ...(config.bearerToken ? { bearerToken: config.bearerToken } : {}),
  });

  const server = new McpServer(
    { name: 'mailcue', version: SERVER_VERSION },
    { instructions: buildInstructions(config) },
  );

  // In locked mode the mailbox is fixed and never exposed as an argument; in
  // multi-mailbox mode every tool requires it.
  const mailboxArg: ZodRawShape = locked
    ? {}
    : {
        mailbox: z
          .string()
          .describe('Mailbox address to act on, e.g. user@example.com.'),
      };

  const resolveMailbox = (provided?: string): string => {
    if (config.mailbox) return config.mailbox;
    const value = provided?.trim();
    if (!value) {
      throw new ToolError(
        'A "mailbox" argument is required. Call list_mailboxes to see available addresses.',
      );
    }
    return value;
  };

  const run = (handler: (args: Record<string, unknown>) => Promise<ToolResult>) => {
    return async (args: Record<string, unknown>): Promise<ToolResult> => {
      try {
        return await handler(args);
      } catch (err) {
        return toolError(describeError(err));
      }
    };
  };

  server.registerTool(
    'list_emails',
    {
      title: 'List emails',
      description:
        'List emails in a mailbox folder, newest first. Returns summaries, each with a uid you can pass to get_email, reply_email, or delete_email.',
      inputSchema: {
        ...mailboxArg,
        folder: FOLDER,
        page: z.number().int().min(1).optional().describe('1-based page number. Default 1.'),
        pageSize: z
          .number()
          .int()
          .min(1)
          .max(200)
          .optional()
          .describe('Results per page. Default 50.'),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { mailbox?: string; folder?: string; page?: number; pageSize?: number };
      const mailbox = resolveMailbox(a.mailbox);
      const folder = a.folder ?? 'INBOX';
      const res = await client.emails.list({
        mailbox,
        folder,
        ...(a.page !== undefined ? { page: a.page } : {}),
        ...(a.pageSize !== undefined ? { pageSize: a.pageSize } : {}),
      });
      return text(formatList(res, folder));
    }),
  );

  server.registerTool(
    'search_emails',
    {
      title: 'Search emails',
      description:
        'Full-text search a mailbox folder by sender, subject, or body content. Returns matching summaries with uids.',
      inputSchema: {
        ...mailboxArg,
        query: z.string().min(1).describe('Text to search for.'),
        folder: FOLDER,
        page: z.number().int().min(1).optional().describe('1-based page number. Default 1.'),
        pageSize: z
          .number()
          .int()
          .min(1)
          .max(200)
          .optional()
          .describe('Results per page. Default 50.'),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as {
        mailbox?: string;
        query: string;
        folder?: string;
        page?: number;
        pageSize?: number;
      };
      const mailbox = resolveMailbox(a.mailbox);
      const folder = a.folder ?? 'INBOX';
      const res = await client.emails.list({
        mailbox,
        folder,
        search: a.query,
        ...(a.page !== undefined ? { page: a.page } : {}),
        ...(a.pageSize !== undefined ? { pageSize: a.pageSize } : {}),
      });
      return text(formatList(res, folder));
    }),
  );

  server.registerTool(
    'get_email',
    {
      title: 'Get email',
      description:
        'Fetch one full email by uid: full body, headers, and attachment metadata. Read this before replying to or deleting a message.',
      inputSchema: {
        ...mailboxArg,
        uid: z.string().describe('The email uid, as returned by list_emails or search_emails.'),
        folder: FOLDER,
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { mailbox?: string; uid: string; folder?: string };
      const mailbox = resolveMailbox(a.mailbox);
      const folder = a.folder ?? 'INBOX';
      const email = await client.emails.get(a.uid, { mailbox, folder });
      return text(formatEmail(email));
    }),
  );

  server.registerTool(
    'send_email',
    {
      title: 'Send email',
      description: locked
        ? `Send a new email from ${config.mailbox}. Provide "text" for plain or "html" for rich (at least one).`
        : 'Send a new email. Provide "text" for plain or "html" for rich (at least one).',
      inputSchema: {
        ...(locked
          ? {}
          : {
              from: z
                .string()
                .describe('Sender mailbox address. You must own this mailbox.'),
            }),
        to: z.array(z.string()).min(1).describe('One or more recipient addresses.'),
        cc: z.array(z.string()).optional().describe('Optional CC recipients.'),
        subject: z.string().describe('Email subject line.'),
        text: z.string().optional().describe('Plain-text body.'),
        html: z.string().optional().describe('HTML body.'),
        replyTo: z.string().optional().describe('Optional Reply-To address.'),
      },
      annotations: { readOnlyHint: false, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as {
        from?: string;
        to: string[];
        cc?: string[];
        subject: string;
        text?: string;
        html?: string;
        replyTo?: string;
      };
      if (a.text === undefined && a.html === undefined) {
        throw new ToolError('Provide at least one of "text" or "html".');
      }
      const from = config.mailbox ?? resolveMailbox(a.from);
      const params: SendEmailParams = { from, to: a.to, subject: a.subject };
      if (a.cc !== undefined) params.cc = a.cc;
      if (a.text !== undefined) params.text = a.text;
      if (a.html !== undefined) params.html = a.html;
      if (a.replyTo !== undefined) params.replyTo = a.replyTo;
      const res = await client.emails.send(params);
      return text(
        JSON.stringify({ status: 'sent', messageId: res.messageId, message: res.message }, null, 2),
      );
    }),
  );

  server.registerTool(
    'reply_email',
    {
      title: 'Reply to email',
      description:
        'Reply to an email by uid. The recipient, the "Re:" subject, and threading headers (In-Reply-To, References) are set for you. Provide "text" or "html".',
      inputSchema: {
        ...mailboxArg,
        uid: z.string().describe('uid of the message to reply to.'),
        folder: FOLDER,
        text: z.string().optional().describe('Plain-text reply body.'),
        html: z.string().optional().describe('HTML reply body.'),
      },
      annotations: { readOnlyHint: false, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as {
        mailbox?: string;
        uid: string;
        folder?: string;
        text?: string;
        html?: string;
      };
      if (a.text === undefined && a.html === undefined) {
        throw new ToolError('Provide at least one of "text" or "html".');
      }
      const mailbox = resolveMailbox(a.mailbox);
      const folder = a.folder ?? 'INBOX';
      const original = await client.emails.get(a.uid, { mailbox, folder });

      const subject = /^re:/i.test(original.subject)
        ? original.subject
        : `Re: ${original.subject}`;
      const params: SendEmailParams = {
        from: mailbox,
        to: [original.fromAddress],
        subject,
      };
      if (original.messageId) {
        params.inReplyTo = original.messageId;
        params.references = [original.messageId];
      }
      if (a.text !== undefined) params.text = a.text;
      if (a.html !== undefined) params.html = a.html;

      const res = await client.emails.send(params);
      return text(
        JSON.stringify(
          { status: 'sent', to: original.fromAddress, subject, messageId: res.messageId },
          null,
          2,
        ),
      );
    }),
  );

  server.registerTool(
    'delete_email',
    {
      title: 'Delete email',
      description:
        'Permanently delete an email by uid. This cannot be undone. Only delete when explicitly asked or clearly required.',
      inputSchema: {
        ...mailboxArg,
        uid: z.string().describe('uid of the message to delete.'),
        folder: FOLDER,
      },
      annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { mailbox?: string; uid: string; folder?: string };
      const mailbox = resolveMailbox(a.mailbox);
      const folder = a.folder ?? 'INBOX';
      await client.emails.delete(a.uid, { mailbox, folder });
      return text(JSON.stringify({ status: 'deleted', uid: a.uid, mailbox, folder }, null, 2));
    }),
  );

  server.registerTool(
    'mailbox_stats',
    {
      title: 'Mailbox stats',
      description: 'Per-folder message counts (total and unread) for a mailbox.',
      inputSchema: { ...mailboxArg },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { mailbox?: string };
      const mailbox = resolveMailbox(a.mailbox);
      const stats = await client.mailboxes.stats(mailbox);
      return text(formatStats(stats));
    }),
  );

  // Discovery only makes sense — and is only safe — when not locked to one box.
  if (!locked) {
    server.registerTool(
      'list_mailboxes',
      {
        title: 'List mailboxes',
        description:
          'List the mailboxes available on this server, with their addresses and unread counts. Use this to choose a "mailbox" argument for the other tools.',
        inputSchema: {},
        annotations: { readOnlyHint: true, openWorldHint: true },
      },
      run(async () => {
        const res = await client.mailboxes.list();
        return text(formatMailboxes(res));
      }),
    );
  }

  return server;
}
