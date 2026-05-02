import type { Transport } from '../transport.js';
import { camelize } from '../transport.js';
import type {
  GpgGenerateParams,
  GpgImportParams,
  GpgKey,
  GpgKeyListResponse,
  GpgPublishResult,
} from '../types.js';

type Opts = { signal?: AbortSignal };

export class GpgResource {
  constructor(private readonly transport: Transport) {}

  async generate(params: GpgGenerateParams, options: Opts = {}): Promise<GpgKey> {
    const body: Record<string, unknown> = {
      mailbox_address: params.mailboxAddress,
      name: params.name ?? 'MailCue User',
      algorithm: params.algorithm ?? 'RSA',
      key_length: params.keyLength ?? 2048,
    };
    if (params.expire !== undefined) body['expire'] = params.expire;
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: '/api/v1/gpg/keys/generate',
      body,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as GpgKey;
  }

  async list(options: Opts = {}): Promise<GpgKeyListResponse> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: '/api/v1/gpg/keys',
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as GpgKeyListResponse;
  }

  async get(address: string, options: Opts = {}): Promise<GpgKey> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: `/api/v1/gpg/keys/${encodeURIComponent(address)}`,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as GpgKey;
  }

  async exportPublic(address: string, options: Opts = {}): Promise<string> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: `/api/v1/gpg/keys/${encodeURIComponent(address)}/export`,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<Record<string, unknown>>(reqOpts);
    const value = raw['public_key'];
    return typeof value === 'string' ? value : '';
  }

  async import(params: GpgImportParams, options: Opts = {}): Promise<GpgKey> {
    const body: Record<string, unknown> = {
      armored_key: params.armoredKey,
    };
    if (params.mailboxAddress !== undefined) body['mailbox_address'] = params.mailboxAddress;
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: '/api/v1/gpg/keys/import',
      body,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as GpgKey;
  }

  async publish(address: string, options: Opts = {}): Promise<GpgPublishResult> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: `/api/v1/gpg/keys/${encodeURIComponent(address)}/publish`,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as GpgPublishResult;
  }

  async delete(address: string, options: Opts = {}): Promise<void> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'DELETE',
      path: `/api/v1/gpg/keys/${encodeURIComponent(address)}`,
      responseType: 'void',
    };
    if (options.signal) reqOpts.signal = options.signal;
    await this.transport.request<void>(reqOpts);
  }
}
