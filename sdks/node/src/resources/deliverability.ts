import type { Transport } from '../transport.js';
import { camelize, snakeify } from '../transport.js';
import type {
  DeliverabilityAlert,
  DeliverabilityCapability,
  DeliverabilityComparison,
  DeliverabilityPolicy,
  DeliverabilityPolicyEvaluation,
  DeliverabilityPolicyParams,
  DeliverabilityProvider,
  DeliverabilityProviderParams,
  DeliverabilityReport,
  DeliverabilityReportList,
  DeliverabilityRun,
  DeliverabilitySchedule,
  DeliverabilityScheduleParams,
  DeliverabilityTrend,
} from '../types.js';

type Opts = { signal?: AbortSignal };

export class DeliverabilityResource {
  constructor(private readonly transport: Transport) {}

  private async json<T>(
    method: 'GET' | 'POST' | 'PUT' | 'DELETE',
    path: string,
    body?: unknown,
    query?: Record<string, unknown>,
    options: Opts = {},
  ): Promise<T> {
    const request: Parameters<Transport['request']>[0] = { method, path };
    if (body !== undefined) request.body = snakeify(body);
    if (query !== undefined) request.query = query;
    if (options.signal) request.signal = options.signal;
    const raw = await this.transport.request<unknown>(request);
    return camelize(raw) as T;
  }

  capabilities(options: Opts = {}): Promise<{ capabilities: DeliverabilityCapability[] }> {
    return this.json('GET', '/api/v1/deliverability/capabilities', undefined, undefined, options);
  }

  history(
    mailbox: string,
    params: { page?: number; pageSize?: number } = {},
    options: Opts = {},
  ): Promise<DeliverabilityReportList> {
    return this.json(
      'GET',
      '/api/v1/deliverability/reports',
      undefined,
      { mailbox, page: params.page, page_size: params.pageSize },
      options,
    );
  }

  report(reportId: string, options: Opts = {}): Promise<DeliverabilityReport> {
    return this.json(
      'GET',
      `/api/v1/deliverability/reports/${encodeURIComponent(reportId)}`,
      undefined,
      undefined,
      options,
    );
  }

  setBaseline(
    reportId: string,
    isBaseline = true,
    options: Opts = {},
  ): Promise<DeliverabilityReport> {
    return this.json(
      'PUT',
      `/api/v1/deliverability/reports/${encodeURIComponent(reportId)}/baseline`,
      { isBaseline },
      undefined,
      options,
    );
  }

  comparison(
    reportId: string,
    beforeReportId?: string,
    options: Opts = {},
  ): Promise<DeliverabilityComparison> {
    return this.json(
      'GET',
      `/api/v1/deliverability/reports/${encodeURIComponent(reportId)}/comparison`,
      undefined,
      { before_report_id: beforeReportId },
      options,
    );
  }

  trend(mailbox: string, limit = 100, options: Opts = {}): Promise<DeliverabilityTrend> {
    return this.json(
      'GET',
      '/api/v1/deliverability/trends',
      undefined,
      { mailbox, limit },
      options,
    );
  }

  run(runId: string, options: Opts = {}): Promise<DeliverabilityRun> {
    return this.json(
      'GET',
      `/api/v1/deliverability/runs/${encodeURIComponent(runId)}`,
      undefined,
      undefined,
      options,
    );
  }

  runsForReport(reportId: string, options: Opts = {}): Promise<DeliverabilityRun[]> {
    return this.json(
      'GET',
      `/api/v1/deliverability/reports/${encodeURIComponent(reportId)}/runs`,
      undefined,
      undefined,
      options,
    );
  }

  async artifact(artifactId: string, options: Opts = {}): Promise<ArrayBuffer> {
    const request: Parameters<Transport['request']>[0] = {
      method: 'GET',
      path: `/api/v1/deliverability/artifacts/${encodeURIComponent(artifactId)}`,
      responseType: 'arrayBuffer',
    };
    if (options.signal) request.signal = options.signal;
    return this.transport.request<ArrayBuffer>(request);
  }

  policies(mailbox: string, options: Opts = {}): Promise<DeliverabilityPolicy[]> {
    return this.json(
      'GET',
      '/api/v1/deliverability/policies',
      undefined,
      { mailbox },
      options,
    );
  }

  createPolicy(
    params: DeliverabilityPolicyParams,
    options: Opts = {},
  ): Promise<DeliverabilityPolicy> {
    return this.json('POST', '/api/v1/deliverability/policies', params, undefined, options);
  }

  updatePolicy(
    policyId: string,
    params: DeliverabilityPolicyParams,
    options: Opts = {},
  ): Promise<DeliverabilityPolicy> {
    return this.json(
      'PUT',
      `/api/v1/deliverability/policies/${encodeURIComponent(policyId)}`,
      params,
      undefined,
      options,
    );
  }

  evaluatePolicy(
    policyId: string,
    reportId: string,
    options: Opts = {},
  ): Promise<DeliverabilityPolicyEvaluation> {
    return this.json(
      'POST',
      `/api/v1/deliverability/policies/${encodeURIComponent(policyId)}/evaluate/${encodeURIComponent(reportId)}`,
      {},
      undefined,
      options,
    );
  }

  deletePolicy(policyId: string, options: Opts = {}): Promise<void> {
    return this.json(
      'DELETE',
      `/api/v1/deliverability/policies/${encodeURIComponent(policyId)}`,
      undefined,
      undefined,
      options,
    );
  }

  providers(options: Opts = {}): Promise<DeliverabilityProvider[]> {
    return this.json('GET', '/api/v1/deliverability/providers', undefined, undefined, options);
  }

  createProvider(
    params: DeliverabilityProviderParams,
    options: Opts = {},
  ): Promise<DeliverabilityProvider> {
    return this.json('POST', '/api/v1/deliverability/providers', params, undefined, options);
  }

  updateProvider(
    providerId: string,
    params: DeliverabilityProviderParams,
    options: Opts = {},
  ): Promise<DeliverabilityProvider> {
    return this.json(
      'PUT',
      `/api/v1/deliverability/providers/${encodeURIComponent(providerId)}`,
      params,
      undefined,
      options,
    );
  }

  deleteProvider(providerId: string, options: Opts = {}): Promise<void> {
    return this.json(
      'DELETE',
      `/api/v1/deliverability/providers/${encodeURIComponent(providerId)}`,
      undefined,
      undefined,
      options,
    );
  }

  schedules(mailbox: string, options: Opts = {}): Promise<DeliverabilitySchedule[]> {
    return this.json(
      'GET',
      '/api/v1/deliverability/schedules',
      undefined,
      { mailbox },
      options,
    );
  }

  createSchedule(
    params: DeliverabilityScheduleParams,
    options: Opts = {},
  ): Promise<DeliverabilitySchedule> {
    return this.json('POST', '/api/v1/deliverability/schedules', params, undefined, options);
  }

  updateSchedule(
    scheduleId: string,
    params: DeliverabilityScheduleParams,
    options: Opts = {},
  ): Promise<DeliverabilitySchedule> {
    return this.json(
      'PUT',
      `/api/v1/deliverability/schedules/${encodeURIComponent(scheduleId)}`,
      params,
      undefined,
      options,
    );
  }

  deleteSchedule(scheduleId: string, options: Opts = {}): Promise<void> {
    return this.json(
      'DELETE',
      `/api/v1/deliverability/schedules/${encodeURIComponent(scheduleId)}`,
      undefined,
      undefined,
      options,
    );
  }

  async alerts(acknowledged?: boolean, options: Opts = {}): Promise<DeliverabilityAlert[]> {
    const response = await this.json<{ alerts: DeliverabilityAlert[] }>(
      'GET',
      '/api/v1/deliverability/alerts',
      undefined,
      { acknowledged },
      options,
    );
    return response.alerts;
  }

  acknowledgeAlert(alertId: string, options: Opts = {}): Promise<DeliverabilityAlert> {
    return this.json(
      'POST',
      `/api/v1/deliverability/alerts/${encodeURIComponent(alertId)}/acknowledge`,
      {},
      undefined,
      options,
    );
  }
}
