import type { Transport } from '../transport.js';
import { camelize } from '../transport.js';
import type {
  Alias,
  AliasCreateParams,
  AliasListResponse,
  AliasUpdateParams,
} from '../types.js';

type Opts = { signal?: AbortSignal };

export class AliasesResource {
  constructor(private readonly transport: Transport) {}

  async list(options: Opts = {}): Promise<AliasListResponse> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: '/api/v1/aliases',
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as AliasListResponse;
  }

  async create(params: AliasCreateParams, options: Opts = {}): Promise<Alias> {
    const body = {
      source_address: params.sourceAddress,
      destination_address: params.destinationAddress,
    };
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'POST',
      path: '/api/v1/aliases',
      body,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as Alias;
  }

  async get(aliasId: number, options: Opts = {}): Promise<Alias> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: `/api/v1/aliases/${aliasId}`,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as Alias;
  }

  async update(aliasId: number, params: AliasUpdateParams, options: Opts = {}): Promise<Alias> {
    const body: Record<string, unknown> = {};
    if (params.destinationAddress !== undefined) {
      body['destination_address'] = params.destinationAddress;
    }
    if (params.enabled !== undefined) body['enabled'] = params.enabled;
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'PUT',
      path: `/api/v1/aliases/${aliasId}`,
      body,
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as Alias;
  }

  async delete(aliasId: number, options: Opts = {}): Promise<void> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'DELETE',
      path: `/api/v1/aliases/${aliasId}`,
      responseType: 'void',
    };
    if (options.signal) reqOpts.signal = options.signal;
    await this.transport.request<void>(reqOpts);
  }
}
