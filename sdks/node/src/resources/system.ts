import type { Transport } from '../transport.js';
import { camelize } from '../transport.js';
import type { CertificateStatus, HealthResponse } from '../types.js';

type Opts = { signal?: AbortSignal };

export class SystemResource {
  constructor(private readonly transport: Transport) {}

  async health(options: Opts = {}): Promise<HealthResponse> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: '/api/v1/health',
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as HealthResponse;
  }

  async getCertificate(options: Opts = {}): Promise<CertificateStatus> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: '/api/v1/system/certificate',
    };
    if (options.signal) reqOpts.signal = options.signal;
    const raw = await this.transport.request<unknown>(reqOpts);
    return camelize(raw) as CertificateStatus;
  }

  async downloadCertificate(options: Opts = {}): Promise<ArrayBuffer> {
    const reqOpts: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: '/api/v1/system/certificate/download',
      responseType: 'arrayBuffer',
    };
    if (options.signal) reqOpts.signal = options.signal;
    return this.transport.request<ArrayBuffer>(reqOpts);
  }
}
