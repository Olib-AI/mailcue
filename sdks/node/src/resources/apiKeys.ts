import type { Transport } from '../transport.js';
import { camelize } from '../transport.js';
import type { ApiKey, ApiKeyCreateParams, ApiKeyCreated, ApiKeyUpdateParams } from '../types.js';

type Opts = { signal?: AbortSignal };

interface ApiKeyListResponse {
  keys: ApiKey[];
  total: number;
}

export class ApiKeysResource {
  constructor(private readonly transport: Transport) {}

  async list(options: Opts = {}): Promise<ApiKeyListResponse> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: '/api/v1/auth/api-keys',
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    if (Array.isArray(raw)) {
      return { keys: camelize(raw) as ApiKey[], total: raw.length };
    }
    return camelize(raw) as ApiKeyListResponse;
  }

  async create(params: ApiKeyCreateParams, options: Opts = {}): Promise<ApiKeyCreated> {
    const body: Record<string, unknown> = { name: params.name };
    if (params.scopes) body.scopes = params.scopes;
    if (params.allowedMailboxes) body.allowed_mailboxes = params.allowedMailboxes;
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: '/api/v1/auth/api-keys',
      body,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as ApiKeyCreated;
  }

  async update(keyId: string, params: ApiKeyUpdateParams, options: Opts = {}): Promise<ApiKey> {
    const body: Record<string, unknown> = {};
    if (params.name !== undefined) body.name = params.name;
    if (params.scopes !== undefined) body.scopes = params.scopes;
    if (params.allowedMailboxes !== undefined) body.allowed_mailboxes = params.allowedMailboxes;
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'PATCH',
      path: `/api/v1/auth/api-keys/${encodeURIComponent(keyId)}`,
      body,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as ApiKey;
  }

  async delete(keyId: string, options: Opts = {}): Promise<void> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'DELETE',
      path: `/api/v1/auth/api-keys/${encodeURIComponent(keyId)}`,
      responseType: 'void',
    };
    if (options.signal) reqOpts.signal = options.signal;
    await this.transport.request<void>(reqOpts);
  }
}
