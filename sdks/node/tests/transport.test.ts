import { describe, expect, it } from 'vitest';
import {
  AuthenticationError,
  AuthorizationError,
  ConflictError,
  Mailcue,
  NotFoundError,
  RateLimitError,
  ServerError,
  ValidationError,
} from '../src/index.js';

function jsonResp(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

describe('transport error mapping', () => {
  it('maps 401 to AuthenticationError', async () => {
    const f = (async () =>
      jsonResp(401, { error: 'bad token' })) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f, maxRetries: 0 });
    await expect(mc.system.health()).rejects.toBeInstanceOf(AuthenticationError);
  });

  it('maps 403 to AuthorizationError (subclass of AuthenticationError)', async () => {
    const f = (async () => jsonResp(403, { error: 'no' })) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f, maxRetries: 0 });
    const err = await mc.system.health().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(AuthorizationError);
    expect(err).toBeInstanceOf(AuthenticationError);
  });

  it('maps 404 to NotFoundError', async () => {
    const f = (async () => jsonResp(404, { error: 'nope' })) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f, maxRetries: 0 });
    await expect(mc.system.health()).rejects.toBeInstanceOf(NotFoundError);
  });

  it('maps 409 to ConflictError', async () => {
    const f = (async () => jsonResp(409, { error: 'dup' })) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f, maxRetries: 0 });
    await expect(mc.system.health()).rejects.toBeInstanceOf(ConflictError);
  });

  it('maps 422 to ValidationError', async () => {
    const f = (async () =>
      jsonResp(422, { detail: [{ msg: 'bad' }] })) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f, maxRetries: 0 });
    await expect(mc.system.health()).rejects.toBeInstanceOf(ValidationError);
  });

  it('maps 429 to RateLimitError and parses Retry-After', async () => {
    const f = (async () =>
      jsonResp(429, { error: 'slow down' }, { 'retry-after': '7' })) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f, maxRetries: 0 });
    const err = (await mc.system.health().catch((e: unknown) => e)) as RateLimitError;
    expect(err).toBeInstanceOf(RateLimitError);
    expect(err.retryAfter).toBe(7);
  });

  it('does not retry on 4xx', async () => {
    let calls = 0;
    const f = (async () => {
      calls++;
      return jsonResp(400, { error: 'bad' });
    }) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f, maxRetries: 3 });
    await expect(mc.system.health()).rejects.toBeInstanceOf(ValidationError);
    expect(calls).toBe(1);
  });

  it('retries on 503 then succeeds', async () => {
    let calls = 0;
    const f = (async () => {
      calls++;
      if (calls < 2) return jsonResp(503, { error: 'down' });
      return jsonResp(200, { status: 'ok' });
    }) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f, maxRetries: 3 });
    const res = await mc.system.health();
    expect(res).toEqual({ status: 'ok' });
    expect(calls).toBe(2);
  });

  it('retries 500 up to maxRetries then throws ServerError', async () => {
    let calls = 0;
    const f = (async () => {
      calls++;
      return jsonResp(503, { error: 'down' });
    }) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f, maxRetries: 2 });
    const err = await mc.system.health().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ServerError);
    expect(calls).toBe(3);
  });

  it('does not retry on 500 (not in retryable set)', async () => {
    let calls = 0;
    const f = (async () => {
      calls++;
      return jsonResp(500, { error: 'boom' });
    }) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f, maxRetries: 3 });
    await expect(mc.system.health()).rejects.toBeInstanceOf(ServerError);
    expect(calls).toBe(1);
  });

  it('returns ArrayBuffer for binary endpoints', async () => {
    const data = new Uint8Array([1, 2, 3, 4]);
    const f = (async () =>
      new Response(data, {
        status: 200,
        headers: { 'content-type': 'application/octet-stream' },
      })) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f });
    const buf = await mc.system.downloadCertificate();
    expect(new Uint8Array(buf)).toEqual(data);
  });

  it('handles 204 No Content for void responses', async () => {
    const f = (async () => new Response(null, { status: 204 })) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f });
    await expect(mc.mailboxes.delete('a@b.com')).resolves.toBeUndefined();
  });
});
