import { TimeoutError } from '../errors.js';
import type { Transport } from '../transport.js';
import { camelize, snakeify } from '../transport.js';
import type {
  BulkInjectResponse,
  EmailDetail,
  EmailListResponse,
  EmailQueryParams,
  EmailSummary,
  InjectEmailParams,
  InjectResult,
  ListEmailsParams,
  SendEmailParams,
  SendResult,
  WaitForEmailParams,
  EmailValidationResponse,
} from '../types.js';

function summaryMatches(email: EmailSummary, p: WaitForEmailParams): boolean {
  if (p.subject && !email.subject.toLowerCase().includes(p.subject.toLowerCase())) return false;
  if (p.from && !email.fromAddress.toLowerCase().includes(p.from.toLowerCase())) return false;
  if (p.to && !email.toAddresses.some((a) => a.toLowerCase().includes(p.to!.toLowerCase())))
    return false;
  return true;
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const t = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(signal?.reason);
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

interface WireSendAttachment {
  filename: string;
  content_type: string;
  data: string;
}

function encodeAttachmentContent(content: Buffer | Uint8Array | string): string {
  if (typeof content === 'string') {
    return Buffer.from(content, 'utf-8').toString('base64');
  }
  if (Buffer.isBuffer(content)) {
    return content.toString('base64');
  }
  return Buffer.from(content).toString('base64');
}

function buildSendBody(params: SendEmailParams): Record<string, unknown> {
  const bodyText = params.text;
  const bodyHtml = params.html;
  let resolvedBody = params.body ?? '';
  let resolvedBodyType = params.bodyType ?? 'plain';
  if (params.body === undefined) {
    if (bodyHtml !== undefined) {
      resolvedBody = bodyHtml;
      resolvedBodyType = 'html';
    } else if (bodyText !== undefined) {
      resolvedBody = bodyText;
      resolvedBodyType = 'plain';
    }
  }

  const wire: Record<string, unknown> = {
    from_address: params.from,
    from_name: params.fromName ?? '',
    to_addresses: params.to,
    cc_addresses: params.cc ?? [],
    subject: params.subject,
    body: resolvedBody,
    body_type: resolvedBodyType,
    sign: params.sign ?? false,
    encrypt: params.encrypt ?? false,
    references: params.references ?? [],
    bulk: params.bulk ?? false,
  };

  if (params.replyTo !== undefined) wire['reply_to'] = params.replyTo;
  if (params.inReplyTo !== undefined) wire['in_reply_to'] = params.inReplyTo;
  if (params.listUnsubscribe !== undefined) wire['list_unsubscribe'] = params.listUnsubscribe;
  if (params.listUnsubscribePost !== undefined) {
    wire['list_unsubscribe_post'] = params.listUnsubscribePost;
  }

  if (params.attachments && params.attachments.length > 0) {
    const out: WireSendAttachment[] = params.attachments.map((a) => ({
      filename: a.filename,
      content_type: a.contentType,
      data: encodeAttachmentContent(a.content),
    }));
    wire['attachments'] = out;
  }

  return wire;
}

export class EmailsResource {
  constructor(private readonly transport: Transport) {}

  async send(params: SendEmailParams, options: { signal?: AbortSignal } = {}): Promise<SendResult> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: '/api/v1/emails/send',
      body: buildSendBody(params),
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<Record<string, string>>(reqOpts);
    return {
      message: raw['message'] ?? '',
      messageId: raw['message_id'] ?? '',
    };
  }

  async list(
    params: ListEmailsParams,
    options: { signal?: AbortSignal } = {},
  ): Promise<EmailListResponse> {
    const query: Record<string, unknown> = {
      mailbox: params.mailbox,
    };
    if (params.folder !== undefined) query['folder'] = params.folder;
    if (params.page !== undefined) query['page'] = params.page;
    if (params.pageSize !== undefined) query['page_size'] = params.pageSize;
    if (params.search !== undefined) query['search'] = params.search;
    if (params.sort !== undefined) query['sort'] = params.sort;

    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: '/api/v1/emails',
      query,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as EmailListResponse;
  }

  async get(
    uid: string,
    params: EmailQueryParams,
    options: { signal?: AbortSignal } = {},
  ): Promise<EmailDetail> {
    const query: Record<string, unknown> = { mailbox: params.mailbox };
    if (params.folder !== undefined) query['folder'] = params.folder;
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: `/api/v1/emails/${encodeURIComponent(uid)}`,
      query,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as EmailDetail;
  }

  async getRaw(
    uid: string,
    params: EmailQueryParams,
    options: { signal?: AbortSignal } = {},
  ): Promise<ArrayBuffer> {
    const query: Record<string, unknown> = { mailbox: params.mailbox };
    if (params.folder !== undefined) query['folder'] = params.folder;
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: `/api/v1/emails/${encodeURIComponent(uid)}/raw`,
      query,
      responseType: 'arrayBuffer',
    };
    if (options.signal) reqOpts.signal = options.signal;
    return this.transport.request<ArrayBuffer>(reqOpts);
  }

  async getAttachment(
    uid: string,
    partId: string,
    params: EmailQueryParams,
    options: { signal?: AbortSignal } = {},
  ): Promise<ArrayBuffer> {
    const query: Record<string, unknown> = { mailbox: params.mailbox };
    if (params.folder !== undefined) query['folder'] = params.folder;
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: `/api/v1/emails/${encodeURIComponent(uid)}/attachments/${encodeURIComponent(partId)}`,
      query,
      responseType: 'arrayBuffer',
    };
    if (options.signal) reqOpts.signal = options.signal;
    return this.transport.request<ArrayBuffer>(reqOpts);
  }

  async delete(
    uid: string,
    params: EmailQueryParams,
    options: { signal?: AbortSignal } = {},
  ): Promise<void> {
    const query: Record<string, unknown> = { mailbox: params.mailbox };
    if (params.folder !== undefined) query['folder'] = params.folder;
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'DELETE',
      path: `/api/v1/emails/${encodeURIComponent(uid)}`,
      query,
      responseType: 'void',
    };
    if (options.signal) reqOpts.signal = options.signal;
    await this.transport.request<void>(reqOpts);
  }

  async inject(
    params: InjectEmailParams,
    options: { signal?: AbortSignal } = {},
  ): Promise<InjectResult> {
    const wire = snakeify({
      ...params,
      fromAddress: params.from,
      toAddresses: params.to,
      ccAddresses: params.cc,
    }) as Record<string, unknown>;
    delete wire['from'];
    delete wire['to'];
    delete wire['cc'];
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: '/api/v1/emails/inject',
      body: wire,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<Record<string, string>>(reqOpts);
    return {
      uid: raw['uid'] ?? '',
      mailbox: raw['mailbox'] ?? '',
    };
  }

  async bulkInject(
    emails: InjectEmailParams[],
    options: { signal?: AbortSignal } = {},
  ): Promise<BulkInjectResponse> {
    const wire = {
      emails: emails.map((p) => {
        const e = snakeify({
          ...p,
          fromAddress: p.from,
          toAddresses: p.to,
          ccAddresses: p.cc,
        }) as Record<string, unknown>;
        delete e['from'];
        delete e['to'];
        delete e['cc'];
        return e;
      }),
    };
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: '/api/v1/emails/bulk-inject',
      body: wire,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as BulkInjectResponse;
  }

  /**
   * Poll a mailbox until matching emails arrive, or throw on timeout.
   *
   * Lists the folder every `intervalMs` and keeps the summaries that match the
   * optional `subject` / `from` / `to` substrings (case-insensitive) on top of
   * the server-side `search`. Resolves with the matches once at least
   * `minCount` are present; rejects with a `TimeoutError` otherwise. Useful for
   * end-to-end tests in CI.
   */
  async waitFor(
    params: WaitForEmailParams,
    options: { signal?: AbortSignal } = {},
  ): Promise<EmailSummary[]> {
    const timeoutMs = params.timeoutMs ?? 10000;
    const intervalMs = params.intervalMs ?? 500;
    const minCount = params.minCount ?? 1;
    const deadline = Date.now() + timeoutMs;

    for (;;) {
      const listParams: ListEmailsParams = { mailbox: params.mailbox };
      if (params.folder !== undefined) listParams.folder = params.folder;
      if (params.search !== undefined) listParams.search = params.search;
      listParams.pageSize = params.pageSize ?? 50;

      const listing = await this.list(listParams, options);
      const matches = listing.emails.filter((e) => summaryMatches(e, params));
      if (matches.length >= minCount) return matches;

      const remaining = deadline - Date.now();
      if (remaining <= 0) {
        throw new TimeoutError(
          `No matching email arrived in mailbox '${params.mailbox}' within ${timeoutMs}ms`,
          timeoutMs,
        );
      }
      await delay(Math.min(intervalMs, remaining), options.signal);
    }
  }

  /**
   * Validate an email address structure, DNS status, mailbox availability, and disposable status.
   */
  async validate(
    email: string,
    options: { signal?: AbortSignal } = {},
  ): Promise<EmailValidationResponse> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: '/api/v1/emails/validate',
      body: { email },
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as EmailValidationResponse;
  }
}
