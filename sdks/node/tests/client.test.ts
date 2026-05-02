import { describe, expect, it } from 'vitest';
import { Mailcue, MailcueError } from '../src/index.js';

describe('Mailcue client', () => {
  it('throws when no auth is provided', () => {
    expect(() => new Mailcue()).toThrow(MailcueError);
  });

  it('constructs with apiKey', () => {
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: globalThis.fetch });
    expect(mc.emails).toBeDefined();
    expect(mc.mailboxes).toBeDefined();
    expect(mc.domains).toBeDefined();
    expect(mc.aliases).toBeDefined();
    expect(mc.gpg).toBeDefined();
    expect(mc.apiKeys).toBeDefined();
    expect(mc.system).toBeDefined();
    expect(mc.events).toBeDefined();
  });

  it('constructs with bearer token', () => {
    const mc = new Mailcue({ bearerToken: 'jwt-token', fetch: globalThis.fetch });
    expect(mc).toBeDefined();
  });

  it('accepts a custom fetch and uses it', async () => {
    const calls: Array<{ url: string; init: RequestInit | undefined }> = [];
    const fakeFetch = (async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }) as unknown as typeof fetch;

    const mc = new Mailcue({
      apiKey: 'mc_test',
      baseUrl: 'https://mail.example.com',
      fetch: fakeFetch,
    });
    const res = await mc.system.health();
    expect(res).toEqual({ status: 'ok' });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe('https://mail.example.com/api/v1/health');
    const headers = calls[0]?.init?.headers as Record<string, string>;
    expect(headers['X-API-Key']).toBe('mc_test');
    expect(headers['User-Agent']).toMatch(/^mailcue-node\//);
  });

  it('uses Bearer header when bearerToken is set', async () => {
    let captured: Headers | undefined;
    const fakeFetch = (async (_url: string, init?: RequestInit) => {
      captured = new Headers(init?.headers as HeadersInit);
      return new Response('{}', {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }) as unknown as typeof fetch;

    const mc = new Mailcue({ bearerToken: 'jwt', fetch: fakeFetch });
    await mc.system.health();
    expect(captured?.get('authorization')).toBe('Bearer jwt');
    expect(captured?.get('x-api-key')).toBeNull();
  });
});
