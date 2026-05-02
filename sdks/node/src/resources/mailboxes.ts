import type { Transport } from '../transport.js';
import { camelize } from '../transport.js';
import type {
  EmailListResponse,
  ListEmailsParams,
  Mailbox,
  MailboxCreateParams,
  MailboxListResponse,
  MailboxStats,
} from '../types.js';

type Opts = { signal?: AbortSignal };

export class MailboxesResource {
  constructor(private readonly transport: Transport) {}

  async list(options: Opts = {}): Promise<MailboxListResponse> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: '/api/v1/mailboxes',
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as MailboxListResponse;
  }

  async create(params: MailboxCreateParams, options: Opts = {}): Promise<Mailbox> {
    const body: Record<string, unknown> = {
      username: params.username,
      password: params.password,
      display_name: params.displayName ?? '',
    };
    if (params.domain !== undefined) body['domain'] = params.domain;
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: '/api/v1/mailboxes',
      body,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as Mailbox;
  }

  async delete(address: string, options: Opts = {}): Promise<void> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'DELETE',
      path: `/api/v1/mailboxes/${encodeURIComponent(address)}`,
      responseType: 'void',
    };
    if (options.signal) reqOpts.signal = options.signal;
    await this.transport.request<void>(reqOpts);
  }

  async stats(mailboxId: string, options: Opts = {}): Promise<MailboxStats> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: `/api/v1/mailboxes/${encodeURIComponent(mailboxId)}/stats`,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as MailboxStats;
  }

  async purge(address: string, options: Opts = {}): Promise<void> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: `/api/v1/mailboxes/${encodeURIComponent(address)}/purge`,
      responseType: 'void',
    };
    if (options.signal) reqOpts.signal = options.signal;
    await this.transport.request<void>(reqOpts);
  }

  async listEmails(
    address: string,
    params: Omit<ListEmailsParams, 'mailbox'> = {},
    options: Opts = {},
  ): Promise<EmailListResponse> {
    const query: Record<string, unknown> = {};
    if (params.folder !== undefined) query['folder'] = params.folder;
    if (params.page !== undefined) query['page'] = params.page;
    if (params.pageSize !== undefined) query['page_size'] = params.pageSize;
    if (params.search !== undefined) query['search'] = params.search;
    if (params.sort !== undefined) query['sort'] = params.sort;
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: `/api/v1/mailboxes/${encodeURIComponent(address)}/emails`,
      query,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as EmailListResponse;
  }
}
