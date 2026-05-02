import { describe, expect, it } from 'vitest';
import { Mailcue } from '../src/index.js';

describe('mailboxes resource', () => {
  it('lists mailboxes and camelizes the response', async () => {
    const f = (async () =>
      new Response(
        JSON.stringify({
          mailboxes: [
            {
              id: '1',
              address: 'a@b.com',
              username: 'a',
              display_name: 'Alice',
              domain: 'b.com',
              is_active: true,
              created_at: '2025-01-01T00:00:00Z',
              quota_mb: 500,
              email_count: 0,
              unread_count: 0,
            },
          ],
          total: 1,
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      )) as unknown as typeof fetch;

    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f });
    const list = await mc.mailboxes.list();
    expect(list.total).toBe(1);
    expect(list.mailboxes[0]!.displayName).toBe('Alice');
    expect(list.mailboxes[0]!.isActive).toBe(true);
    expect(list.mailboxes[0]!.quotaMb).toBe(500);
  });

  it('creates a mailbox with snake_cased body', async () => {
    let captured: Record<string, unknown> | undefined;
    const f = (async (_url: string, init?: RequestInit) => {
      captured = JSON.parse(init?.body as string);
      return new Response(
        JSON.stringify({
          id: '1',
          address: 'a@b.com',
          username: 'a',
          display_name: 'A',
          domain: 'b.com',
          is_active: true,
          created_at: '2025-01-01T00:00:00Z',
        }),
        { status: 201, headers: { 'content-type': 'application/json' } },
      );
    }) as unknown as typeof fetch;

    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f });
    const out = await mc.mailboxes.create({
      username: 'a',
      password: 'pw',
      domain: 'b.com',
      displayName: 'A',
    });
    expect(out.address).toBe('a@b.com');
    expect(captured?.['display_name']).toBe('A');
    expect(captured?.['username']).toBe('a');
    expect(captured?.['domain']).toBe('b.com');
  });

  it('encodes addresses with @ in the path', async () => {
    let url: string | undefined;
    const f = (async (u: string) => {
      url = u;
      return new Response(null, { status: 204 });
    }) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f });
    await mc.mailboxes.delete('user@example.com');
    expect(url).toBe('http://localhost:8088/api/v1/mailboxes/user%40example.com');
  });
});
