import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import {
  AuthenticationError,
  AuthorizationError,
  Mailcue,
  MailcueError,
  type CreateSendCanaryParams,
  type SendEmailParams,
} from 'mailcue';
import { z, type ZodRawShape } from 'zod';

import { isLocked, type McpConfig } from './config.js';
import {
  formatEmail,
  formatList,
  formatMailboxes,
  formatStats,
} from './format.js';
import { buildInstructions } from './instructions.js';

export const SERVER_VERSION = '0.1.6';

type ToolResult = {
  content: Array<
    | { type: 'text'; text: string }
    | { type: 'image'; data: string; mimeType: string }
  >;
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

// Matches the backend's "... missing the required 'email:send' permission".
const MISSING_SCOPE_RE = /required '([^']+)' permission/;

function describeError(err: unknown): string {
  if (err instanceof ToolError) return err.message;
  // Permission failures (403): the key is authenticated but not allowed to do
  // this. Tell the model exactly what is missing so it stops retrying.
  // AuthorizationError is the SDK's 403 type (the newer PermissionError
  // subclasses it, so this also covers SDKs that expose a parsed scope).
  if (err instanceof AuthorizationError) {
    const scope =
      (err as { scope?: string }).scope ?? MISSING_SCOPE_RE.exec(err.message)?.[1];
    if (scope) {
      return (
        `Permission denied: this MailCue API key does not have the "${scope}" ` +
        `permission required for this action. Use a key that includes it, or ask ` +
        `the key owner to grant it. This will not succeed on retry.`
      );
    }
    if (/mailbox/i.test(err.message)) {
      return (
        'Permission denied: this MailCue API key is restricted to specific ' +
        'mailboxes and is not allowed to access this one. Use an allowed mailbox, ' +
        'or ask the key owner to widen the key. This will not succeed on retry.'
      );
    }
    return `Permission denied: ${err.message}. This will not succeed on retry.`;
  }
  // Auth failures (401): missing/invalid credentials. AuthorizationError is
  // checked first above since it also extends AuthenticationError.
  if (err instanceof AuthenticationError) {
    return (
      'Authentication failed: the MailCue API key or bearer token is missing or ' +
      'invalid. Check the MAILCUE_API_KEY / MAILCUE_BEARER_TOKEN configuration.'
    );
  }
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

  const scoreDeliverability = async (mailbox: string, uid: string, folder: string) => {
    const base = config.baseUrl.replace(/\/+$/, '');
    const url = new URL(
      `${base}/api/v1/mailboxes/${encodeURIComponent(mailbox)}/emails/${encodeURIComponent(uid)}/deliverability`,
    );
    url.searchParams.set('folder', folder);
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (config.apiKey) headers['X-API-Key'] = config.apiKey;
    if (config.bearerToken) headers['Authorization'] = `Bearer ${config.bearerToken}`;
    const response = await fetch(url, { headers });
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const body = (await response.json()) as { detail?: string };
        if (body.detail) detail = body.detail;
      } catch {
        // Keep the bounded HTTP status when the server did not return JSON.
      }
      throw new ToolError(`MailCue deliverability request failed: ${detail}`);
    }
    return response.json() as Promise<unknown>;
  };

  const runDeliverabilityChecks = async (
    mailbox: string,
    uid: string,
    folder: string,
    checks: string[],
  ) => {
    const base = config.baseUrl.replace(/\/+$/, '');
    const url = new URL(
      `${base}/api/v1/mailboxes/${encodeURIComponent(mailbox)}/emails/${encodeURIComponent(uid)}/deliverability/runs`,
    );
    url.searchParams.set('folder', folder);
    const headers: Record<string, string> = {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    };
    if (config.apiKey) headers['X-API-Key'] = config.apiKey;
    if (config.bearerToken) headers['Authorization'] = `Bearer ${config.bearerToken}`;
    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({ checks }),
    });
    if (!response.ok) {
      throw new ToolError(`MailCue deliverability enrichment failed: HTTP ${response.status}`);
    }
    return response.json() as Promise<unknown>;
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
    'score_email_deliverability',
    {
      title: 'Score email deliverability',
      description:
        'Score one received email from its original message bytes. Returns a 0 to 100 score, category breakdown, evidence, and prioritized fixes for authentication, content, headers, transport, and the local spam filter.',
      inputSchema: {
        ...mailboxArg,
        uid: z.string().describe('The email uid returned by list_emails or search_emails.'),
        folder: FOLDER,
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { mailbox?: string; uid: string; folder?: string };
      const mailbox = resolveMailbox(a.mailbox);
      const report = await scoreDeliverability(mailbox, a.uid, a.folder ?? 'INBOX');
      return text(JSON.stringify(report, null, 2));
    }),
  );

  server.registerTool(
    'run_email_deliverability_checks',
    {
      title: 'Run extended deliverability checks',
      description:
        'Run configured DNS, reputation, live-link, visual, placement, client-preview, or advisory AI analysis checks for one received email. Capabilities that are disabled or not configured are reported truthfully.',
      inputSchema: {
        ...mailboxArg,
        uid: z.string().describe('The email uid returned by list_emails or search_emails.'),
        folder: FOLDER,
        checks: z
          .array(
            z.enum(['dns', 'reputation', 'links', 'visual', 'placement', 'client_previews', 'ai_analysis']),
          )
          .min(1)
          .max(7)
          .default(['dns', 'reputation']),
      },
      annotations: { readOnlyHint: false, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { mailbox?: string; uid: string; folder?: string; checks: string[] };
      const mailbox = resolveMailbox(a.mailbox);
      const result = await runDeliverabilityChecks(
        mailbox,
        a.uid,
        a.folder ?? 'INBOX',
        a.checks,
      );
      return text(JSON.stringify(result, null, 2));
    }),
  );

  server.registerTool(
    'get_deliverability_capabilities',
    {
      title: 'Get deliverability capabilities',
      description:
        'Show which local, network, visual, placement, real-client preview, and AI analysis capabilities are available, disabled, or not configured on this MailCue deployment.',
      inputSchema: {},
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    run(async () => text(JSON.stringify(await client.deliverability.capabilities(), null, 2))),
  );

  server.registerTool(
    'list_deliverability_reports',
    {
      title: 'List deliverability reports',
      description: 'List persisted versioned score reports for a deliverability mailbox.',
      inputSchema: {
        ...mailboxArg,
        page: z.number().int().min(1).optional(),
        pageSize: z.number().int().min(1).max(200).optional(),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    run(async (args) => {
      const a = args as { mailbox?: string; page?: number; pageSize?: number };
      const result = await client.deliverability.history(resolveMailbox(a.mailbox), {
        ...(a.page !== undefined ? { page: a.page } : {}),
        ...(a.pageSize !== undefined ? { pageSize: a.pageSize } : {}),
      });
      return text(JSON.stringify(result, null, 2));
    }),
  );

  server.registerTool(
    'list_deliverability_runs',
    {
      title: 'List extended deliverability runs',
      description:
        'List persisted DNS, link, visual, placement, client-preview, and advisory AI runs for one report.',
      inputSchema: {
        reportId: z.string().describe('The persisted report id returned by a scoring or history tool.'),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    run(async (args) => {
      const a = args as { reportId: string };
      return text(
        JSON.stringify(await client.deliverability.runsForReport(a.reportId), null, 2),
      );
    }),
  );

  server.registerTool(
    'get_deliverability_artifact',
    {
      title: 'Get deliverability image artifact',
      description:
        'Fetch a protected local render, attention estimate, or provider preview as MCP image content.',
      inputSchema: {
        artifactId: z.string().describe('The artifact id from an extended run evidence URL.'),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    run(async (args) => {
      const a = args as { artifactId: string };
      const bytes = new Uint8Array(await client.deliverability.artifact(a.artifactId));
      const mimeType =
        bytes.length >= 8 &&
        bytes[0] === 0x89 &&
        bytes[1] === 0x50 &&
        bytes[2] === 0x4e &&
        bytes[3] === 0x47
          ? 'image/png'
          : bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff
            ? 'image/jpeg'
            : null;
      if (mimeType === null) return toolError('The artifact is not a supported PNG or JPEG image.');
      return {
        content: [
          {
            type: 'image' as const,
            data: Buffer.from(bytes).toString('base64'),
            mimeType,
          },
        ],
      };
    }),
  );

  server.registerTool(
    'compare_deliverability_reports',
    {
      title: 'Compare deliverability reports',
      description:
        'Compare one persisted report with an explicit earlier report, the selected baseline, or the previous report.',
      inputSchema: {
        reportId: z.string().uuid(),
        beforeReportId: z.string().uuid().optional(),
      },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    run(async (args) => {
      const a = args as { reportId: string; beforeReportId?: string };
      return text(
        JSON.stringify(
          await client.deliverability.comparison(a.reportId, a.beforeReportId),
          null,
          2,
        ),
      );
    }),
  );

  server.registerTool(
    'create_deliverability_policy',
    {
      title: 'Create a deliverability policy',
      description:
        'Create a mailbox CI gate for minimum score, maximum regression, blocked statuses, required checks, and required deployment capabilities.',
      inputSchema: {
        ...mailboxArg,
        name: z.string().min(1).max(120),
        minimumScore: z.number().int().min(0).max(100).default(80),
        maximumRegression: z.number().int().min(0).max(100).default(5),
        failOnStatuses: z.array(z.enum(['warning', 'fail'])).default(['fail']),
        requiredCheckIds: z.array(z.string()).max(100).default([]),
        requiredCapabilities: z.array(z.string()).max(30).default([]),
      },
      annotations: { readOnlyHint: false, openWorldHint: false },
    },
    run(async (args) => {
      const a = args as {
        mailbox?: string;
        name: string;
        minimumScore: number;
        maximumRegression: number;
        failOnStatuses: Array<'warning' | 'fail'>;
        requiredCheckIds: string[];
        requiredCapabilities: string[];
      };
      const result = await client.deliverability.createPolicy({
        mailbox: resolveMailbox(a.mailbox),
        name: a.name,
        minimumScore: a.minimumScore,
        maximumRegression: a.maximumRegression,
        failOnStatuses: a.failOnStatuses,
        requiredCheckIds: a.requiredCheckIds,
        requiredCapabilities: a.requiredCapabilities,
      });
      return text(JSON.stringify(result, null, 2));
    }),
  );

  server.registerTool(
    'evaluate_deliverability_policy',
    {
      title: 'Evaluate a deliverability policy',
      description: 'Evaluate a persisted report against a CI policy and create an alert on failure.',
      inputSchema: { policyId: z.string().uuid(), reportId: z.string().uuid() },
      annotations: { readOnlyHint: false, openWorldHint: false },
    },
    run(async (args) => {
      const a = args as { policyId: string; reportId: string };
      return text(
        JSON.stringify(
          await client.deliverability.evaluatePolicy(a.policyId, a.reportId),
          null,
          2,
        ),
      );
    }),
  );

  server.registerTool(
    'list_deliverability_alerts',
    {
      title: 'List deliverability alerts',
      description: 'List policy, schedule, and provider alerts for the authenticated user.',
      inputSchema: { acknowledged: z.boolean().optional() },
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    run(async (args) => {
      const a = args as { acknowledged?: boolean };
      return text(
        JSON.stringify(await client.deliverability.alerts(a.acknowledged), null, 2),
      );
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
        fromName: z
          .string()
          .optional()
          .describe(
            'Display name recipients see. Omit to use the name set on the mailbox, which is almost always what you want.',
          ),
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
        fromName?: string;
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
      // Left unset the server falls back to the mailbox's own display name, so
      // this is an override rather than the source of the name.
      if (a.fromName !== undefined) params.fromName = a.fromName;
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

  server.registerTool(
    'validate_email',
    {
      title: 'Validate email address',
      description:
        'Validate structure, DNS, SMTP acceptance, disposable status, and catch-all risk. The result also identifies the receiving provider, what the control recipients proved, and the local-part and domain signals behind the score.',
      inputSchema: {
        email: z.string().describe('The email address to validate.'),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { email: string };
      const res = await client.emails.validate(a.email);
      return text(JSON.stringify(res, null, 2));
    }),
  );

  server.registerTool(
    'record_validation_feedback',
    {
      title: 'Record email validation feedback',
      description:
        'Record an organic delivery, hard bounce, or soft bounce to improve tenant-specific catch-all risk scoring.',
      inputSchema: {
        email: z.string().describe('The recipient email address.'),
        outcome: z.enum(['delivered', 'hard_bounce', 'soft_bounce']),
        smtpCode: z.number().int().min(100).max(599).optional(),
        enhancedStatus: z.string().max(16).optional(),
      },
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as {
        email: string;
        outcome: 'delivered' | 'hard_bounce' | 'soft_bounce';
        smtpCode?: number;
        enhancedStatus?: string;
      };
      const res = await client.emails.recordValidationFeedback(a);
      return text(JSON.stringify(res, null, 2));
    }),
  );

  server.registerTool(
    'validate_email_batch',
    {
      title: 'Validate a batch of email addresses',
      description:
        'Validate many addresses at once. Addresses at the same domain reveal that domain\'s ' +
        'naming convention and any generated name variants, neither of which is visible one ' +
        'address at a time. Set targetBounceRate to also get the largest subset whose blended ' +
        'expected bounce rate stays under that ceiling, which is what actually protects sender ' +
        'reputation.',
      inputSchema: {
        emails: z.array(z.string()).min(1).describe('Addresses to validate.'),
        targetBounceRate: z
          .number()
          .min(0)
          .max(1)
          .optional()
          .describe('Blended bounce-rate ceiling for the returned selection, e.g. 0.015.'),
        includeDomainSignals: z.boolean().optional(),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as {
        emails: string[];
        targetBounceRate?: number;
        includeDomainSignals?: boolean;
      };
      const res = await client.emails.validateBatch(a);
      return text(JSON.stringify(res, null, 2));
    }),
  );

  server.registerTool(
    'get_validation_calibration',
    {
      title: 'Check validation score calibration',
      description:
        'Report how well previously issued risk scores matched the outcomes that followed, as a ' +
        'Brier score and reliability bins. A score is only a probability once it has been ' +
        'checked against reality.',
      inputSchema: {
        days: z.number().int().min(1).max(365).optional(),
        scope: z.enum(['tenant', 'global']).optional(),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { days?: number; scope?: 'tenant' | 'global' };
      const res = await client.emails.validationCalibration(a);
      return text(JSON.stringify(res, null, 2));
    }),
  );

  server.registerTool(
    'ingest_bounce',
    {
      title: 'Record outcomes from a bounce message',
      description:
        'Parse a raw delivery status notification and record the recipient outcomes it carries. ' +
        'A bounce is the only ground truth that exists for a recipient no probe could classify.',
      inputSchema: {
        rawMessage: z.string().min(1).describe('The raw RFC 5322 notification.'),
      },
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { rawMessage: string };
      const res = await client.emails.ingestBounce(a.rawMessage);
      return text(JSON.stringify(res, null, 2));
    }),
  );

  server.registerTool(
    'list_suppressed_domains',
    {
      title: 'List suppressed recipient domains',
      description:
        'List recipient domains paused for sending after their measured hard-bounce rate crossed ' +
        'the circuit-breaker limit.',
      inputSchema: {},
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    run(async () => {
      const res = await client.emails.suppressedDomains();
      return text(JSON.stringify(res, null, 2));
    }),
  );

  server.registerTool(
    'create_send_canary',
    {
      title: 'Stage a send behind a canary sample',
      description:
        'Send to a small sample first, watch the bounce window, and release the rest only if the ' +
        'sample survived. A message cannot be recalled once it leaves the MTA, so the only ' +
        'control on an accept-all domain is how much of the batch is committed at once.',
      inputSchema: {
        recipients: z.array(z.string()).min(1),
        fromAddress: z.string(),
        subject: z.string(),
        body: z.string().optional(),
        name: z.string().optional(),
        fromName: z.string().optional(),
        bodyType: z.enum(['plain', 'html']).optional(),
        replyTo: z.string().optional(),
        sampleSize: z.number().int().min(1).max(50).optional(),
        holdMinutes: z.number().int().min(1).max(10080).optional(),
        bounceThreshold: z.number().min(0).max(1).optional(),
        autoRelease: z.boolean().optional(),
      },
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as unknown as CreateSendCanaryParams;
      const res = await client.emails.createSendCanary(a);
      return text(JSON.stringify(res, null, 2));
    }),
  );

  server.registerTool(
    'get_send_canary',
    {
      title: 'Inspect a staged send',
      description:
        'Return the state of one staged send: which recipients were sampled, what came back, and ' +
        'whether the remainder was released or withheld.',
      inputSchema: {
        canaryId: z.string(),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { canaryId: string };
      const res = await client.emails.getSendCanary(a.canaryId);
      return text(JSON.stringify(res, null, 2));
    }),
  );

  server.registerTool(
    'list_send_canaries',
    {
      title: 'List staged sends',
      description: 'List staged sends for this account, newest first.',
      inputSchema: {
        limit: z.number().int().min(1).max(100).optional(),
      },
      annotations: { readOnlyHint: true, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { limit?: number };
      const res = await client.emails.listSendCanaries(a);
      return text(JSON.stringify(res, null, 2));
    }),
  );

  server.registerTool(
    'decide_send_canary',
    {
      title: 'Resolve a staged send now',
      description:
        'Apply the hold-window verdict immediately instead of waiting for it to elapse. A clean ' +
        'sample releases everything, a wholly failed sample withholds everything, and a partly ' +
        'failed sample releases only the addresses scored safer than the ones that bounced.',
      inputSchema: {
        canaryId: z.string(),
      },
      annotations: { readOnlyHint: false, destructiveHint: false, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { canaryId: string };
      const res = await client.emails.decideSendCanary(a.canaryId);
      return text(JSON.stringify(res, null, 2));
    }),
  );

  server.registerTool(
    'cancel_send_canary',
    {
      title: 'Cancel a staged send',
      description: 'Stop a staged send before its remaining recipients go out.',
      inputSchema: {
        canaryId: z.string(),
      },
      annotations: { readOnlyHint: false, destructiveHint: true, openWorldHint: true },
    },
    run(async (args) => {
      const a = args as { canaryId: string };
      const res = await client.emails.cancelSendCanary(a.canaryId);
      return text(JSON.stringify(res, null, 2));
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
