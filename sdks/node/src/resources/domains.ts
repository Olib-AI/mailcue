import type { Transport } from '../transport.js';
import { camelize } from '../transport.js';
import type {
  DnsCheckResponse,
  Domain,
  DomainCreateParams,
  DomainDetail,
  DomainListResponse,
} from '../types.js';

type Opts = { signal?: AbortSignal };

export class DomainsResource {
  constructor(private readonly transport: Transport) {}

  async list(options: Opts = {}): Promise<DomainListResponse> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: '/api/v1/domains',
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as DomainListResponse;
  }

  async create(params: DomainCreateParams, options: Opts = {}): Promise<Domain> {
    const body: Record<string, unknown> = { name: params.name };
    if (params.dkimSelector !== undefined) body['dkim_selector'] = params.dkimSelector;
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: '/api/v1/domains',
      body,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as Domain;
  }

  async get(name: string, options: Opts = {}): Promise<DomainDetail> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: `/api/v1/domains/${encodeURIComponent(name)}`,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as DomainDetail;
  }

  async verifyDns(name: string, options: Opts = {}): Promise<DnsCheckResponse> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: `/api/v1/domains/${encodeURIComponent(name)}/verify-dns`,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as DnsCheckResponse;
  }

  async delete(name: string, options: Opts = {}): Promise<void> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'DELETE',
      path: `/api/v1/domains/${encodeURIComponent(name)}`,
      responseType: 'void',
    };
    if (options.signal) reqOpts.signal = options.signal;
    await this.transport.request<void>(reqOpts);
  }
}
