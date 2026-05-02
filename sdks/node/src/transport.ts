import {
  AuthenticationError,
  AuthorizationError,
  ConflictError,
  MailcueError,
  NetworkError,
  NotFoundError,
  RateLimitError,
  ServerError,
  TimeoutError,
  ValidationError,
} from './errors.js';
import { buildAuthHeaders, type AuthConfig } from './auth.js';

export type FetchLike = typeof fetch;

export interface TransportOptions {
  baseUrl: string;
  auth: AuthConfig;
  timeout: number;
  maxRetries: number;
  fetch: FetchLike;
  userAgent: string;
}

export interface RequestOptions {
  method?: string;
  path: string;
  query?: Record<string, unknown>;
  body?: unknown;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  responseType?: 'json' | 'arrayBuffer' | 'text' | 'void';
}

const RETRY_STATUS = new Set([502, 503, 504]);
const BASE_DELAY_MS = 500;
const MAX_DELAY_MS = 8000;

function jitter(value: number): number {
  const factor = 1 + (Math.random() * 0.4 - 0.2);
  return Math.floor(value * factor);
}

function backoff(attempt: number): number {
  const exp = BASE_DELAY_MS * 2 ** attempt;
  return Math.min(MAX_DELAY_MS, jitter(exp));
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
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

export function buildQuery(query: Record<string, unknown> | undefined): string {
  if (!query) return '';
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const v of value) sp.append(key, String(v));
    } else {
      sp.append(key, String(value));
    }
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export function camelToSnake(key: string): string {
  return key.replace(/[A-Z]/g, (m) => `_${m.toLowerCase()}`);
}

export function snakeToCamel(key: string): string {
  return key.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== 'object') return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

export function snakeify(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(snakeify);
  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      out[camelToSnake(k)] = snakeify(v);
    }
    return out;
  }
  return value;
}

export function camelize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(camelize);
  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      out[snakeToCamel(k)] = camelize(v);
    }
    return out;
  }
  return value;
}

interface ParsedError {
  message: string;
  body: unknown;
}

async function parseError(res: Response): Promise<ParsedError> {
  const text = await res.text().catch(() => '');
  if (!text) {
    return { message: `HTTP ${res.status}`, body: null };
  }
  try {
    const json: unknown = JSON.parse(text);
    if (json && typeof json === 'object') {
      const obj = json as Record<string, unknown>;
      const msg =
        (typeof obj['error'] === 'string' && obj['error']) ||
        (typeof obj['message'] === 'string' && obj['message']) ||
        (typeof obj['detail'] === 'string' && obj['detail']) ||
        `HTTP ${res.status}`;
      return { message: msg, body: json };
    }
    return { message: String(json), body: json };
  } catch {
    return { message: text, body: text };
  }
}

function parseRetryAfter(value: string | null): number | undefined {
  if (!value) return undefined;
  const n = Number(value);
  if (!Number.isNaN(n)) return Math.max(0, Math.floor(n));
  const date = Date.parse(value);
  if (!Number.isNaN(date)) {
    return Math.max(0, Math.ceil((date - Date.now()) / 1000));
  }
  return undefined;
}

function mapHttpError(status: number, parsed: ParsedError, requestId?: string): MailcueError {
  const ctx = { status, body: parsed.body, ...(requestId ? { requestId } : {}) };
  if (status === 400 || status === 422) return new ValidationError(parsed.message, ctx);
  if (status === 401) return new AuthenticationError(parsed.message, ctx);
  if (status === 403) return new AuthorizationError(parsed.message, ctx);
  if (status === 404) return new NotFoundError(parsed.message, ctx);
  if (status === 409) return new ConflictError(parsed.message, ctx);
  if (status >= 500) return new ServerError(parsed.message, ctx);
  return new MailcueError(parsed.message, ctx);
}

export class Transport {
  private readonly baseUrl: string;
  private readonly auth: AuthConfig;
  private readonly timeout: number;
  private readonly maxRetries: number;
  private readonly fetchImpl: FetchLike;
  private readonly userAgent: string;

  constructor(opts: TransportOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, '');
    this.auth = opts.auth;
    this.timeout = opts.timeout;
    this.maxRetries = opts.maxRetries;
    this.fetchImpl = opts.fetch;
    this.userAgent = opts.userAgent;
  }

  async request<T = unknown>(opts: RequestOptions): Promise<T> {
    const method = opts.method ?? 'GET';
    const url = `${this.baseUrl}${opts.path}${buildQuery(opts.query)}`;
    const responseType = opts.responseType ?? 'json';

    const headers: Record<string, string> = {
      Accept: 'application/json',
      'User-Agent': this.userAgent,
      ...buildAuthHeaders(this.auth),
      ...(opts.headers ?? {}),
    };

    let bodyInit: BodyInit | undefined;
    if (opts.body !== undefined && opts.body !== null) {
      if (
        typeof opts.body === 'string' ||
        opts.body instanceof Uint8Array ||
        opts.body instanceof ArrayBuffer
      ) {
        bodyInit = opts.body as BodyInit;
      } else {
        headers['Content-Type'] = headers['Content-Type'] ?? 'application/json';
        bodyInit = JSON.stringify(opts.body);
      }
    }

    let lastError: unknown;
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(new Error('timeout')), this.timeout);

      const onUserAbort = () => controller.abort(opts.signal?.reason);
      if (opts.signal) {
        if (opts.signal.aborted) {
          clearTimeout(timeoutId);
          throw opts.signal.reason instanceof Error
            ? opts.signal.reason
            : new MailcueError('Request aborted');
        }
        opts.signal.addEventListener('abort', onUserAbort, { once: true });
      }

      try {
        const init: RequestInit = {
          method,
          headers,
          signal: controller.signal,
        };
        if (bodyInit !== undefined) init.body = bodyInit;
        const res = await this.fetchImpl(url, init);

        if (res.ok) {
          if (responseType === 'arrayBuffer') {
            return (await res.arrayBuffer()) as T;
          }
          if (responseType === 'text') {
            return (await res.text()) as T;
          }
          if (responseType === 'void' || res.status === 204) {
            await res.body?.cancel().catch(() => undefined);
            return undefined as T;
          }
          const ct = res.headers.get('content-type') ?? '';
          if (!ct.includes('application/json')) {
            const text = await res.text();
            return (text ? text : undefined) as T;
          }
          return (await res.json()) as T;
        }

        const requestId = res.headers.get('x-request-id') ?? undefined;
        if (res.status === 429) {
          const retryAfter = parseRetryAfter(res.headers.get('retry-after'));
          const parsed = await parseError(res);
          throw new RateLimitError(parsed.message, {
            status: 429,
            body: parsed.body,
            ...(requestId ? { requestId } : {}),
            ...(retryAfter !== undefined ? { retryAfter } : {}),
          });
        }

        const parsed = await parseError(res);
        const err = mapHttpError(res.status, parsed, requestId);

        if (RETRY_STATUS.has(res.status) && attempt < this.maxRetries) {
          lastError = err;
          await sleep(backoff(attempt), opts.signal);
          continue;
        }
        throw err;
      } catch (err) {
        if (err instanceof MailcueError) {
          if (
            err instanceof ServerError &&
            attempt < this.maxRetries &&
            RETRY_STATUS.has(err.status ?? 0)
          ) {
            lastError = err;
            await sleep(backoff(attempt), opts.signal);
            continue;
          }
          throw err;
        }

        const aborted =
          (err instanceof Error && (err.name === 'AbortError' || err.name === 'TimeoutError')) ||
          controller.signal.aborted;

        if (aborted) {
          if (opts.signal?.aborted) {
            throw opts.signal.reason instanceof Error
              ? opts.signal.reason
              : new MailcueError('Request aborted');
          }
          throw new TimeoutError(`Request timed out after ${this.timeout}ms`, this.timeout);
        }

        if (attempt < this.maxRetries) {
          lastError = err;
          await sleep(backoff(attempt), opts.signal);
          continue;
        }
        throw new NetworkError(
          err instanceof Error ? err.message : 'Network request failed',
          err,
        );
      } finally {
        clearTimeout(timeoutId);
        opts.signal?.removeEventListener('abort', onUserAbort);
      }
    }

    if (lastError instanceof MailcueError) throw lastError;
    throw new NetworkError(
      lastError instanceof Error ? lastError.message : 'Network request failed',
      lastError,
    );
  }

  async stream(opts: RequestOptions): Promise<Response> {
    const url = `${this.baseUrl}${opts.path}${buildQuery(opts.query)}`;
    const headers: Record<string, string> = {
      Accept: 'text/event-stream',
      'User-Agent': this.userAgent,
      ...buildAuthHeaders(this.auth),
      ...(opts.headers ?? {}),
    };
    const init: RequestInit = {
      method: opts.method ?? 'GET',
      headers,
    };
    if (opts.signal) init.signal = opts.signal;
    try {
      const res = await this.fetchImpl(url, init);
      if (!res.ok) {
        const requestId = res.headers.get('x-request-id') ?? undefined;
        if (res.status === 429) {
          const retryAfter = parseRetryAfter(res.headers.get('retry-after'));
          const parsed = await parseError(res);
          throw new RateLimitError(parsed.message, {
            status: 429,
            body: parsed.body,
            ...(requestId ? { requestId } : {}),
            ...(retryAfter !== undefined ? { retryAfter } : {}),
          });
        }
        const parsed = await parseError(res);
        throw mapHttpError(res.status, parsed, requestId);
      }
      return res;
    } catch (err) {
      if (err instanceof MailcueError) throw err;
      throw new NetworkError(
        err instanceof Error ? err.message : 'Network request failed',
        err,
      );
    }
  }
}
