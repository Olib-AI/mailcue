import { describe, expect, it } from 'vitest';
import { Mailcue } from '../src/index.js';

interface Call {
  url: string;
  method: string;
  body: unknown;
}

function clientWith(response: Response): { client: Mailcue; calls: Call[] } {
  const calls: Call[] = [];
  const fakeFetch = (async (url: string, init?: RequestInit) => {
    let body: unknown;
    if (typeof init?.body === 'string') body = JSON.parse(init.body);
    calls.push({ url, method: init?.method ?? 'GET', body });
    return response.clone();
  }) as unknown as typeof fetch;
  return { client: new Mailcue({ apiKey: 'mc_test', fetch: fakeFetch }), calls };
}

describe('deliverability resource', () => {
  it('lists persisted report history with encoded pagination', async () => {
    const { client, calls } = clientWith(
      new Response(
        JSON.stringify({ reports: [], total: 0, page: 2, page_size: 25, has_more: false }),
        { headers: { 'content-type': 'application/json' } },
      ),
    );

    const result = await client.deliverability.history('score+ci@example.com', {
      page: 2,
      pageSize: 25,
    });

    expect(result.pageSize).toBe(25);
    expect(calls[0]!.url).toContain('mailbox=score%2Bci%40example.com');
    expect(calls[0]!.url).toContain('page_size=25');
  });

  it('snake-cases policy and analysis-provider contracts', async () => {
    const { client, calls } = clientWith(
      new Response(JSON.stringify({ id: 'created' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    );

    await client.deliverability.createPolicy({
      name: 'Release gate',
      mailbox: 'score@example.com',
      minimumScore: 90,
      requiredCheckIds: ['spf', 'dkim'],
    });
    await client.deliverability.createProvider({
      name: 'Copy review',
      kind: 'analysis',
      adapter: 'generic_http_analysis',
      config: { baseUrl: 'https://analysis.example.com/review' },
      secret: 'write-only',
    });

    expect(calls[0]!.body).toMatchObject({
      minimum_score: 90,
      required_check_ids: ['spf', 'dkim'],
    });
    expect(calls[1]!.body).toMatchObject({
      adapter: 'generic_http_analysis',
      config: { base_url: 'https://analysis.example.com/review' },
    });
  });

  it('downloads protected artifacts as binary data', async () => {
    const bytes = new Uint8Array([137, 80, 78, 71]);
    const { client, calls } = clientWith(new Response(bytes));

    const result = await client.deliverability.artifact('artifact/id');

    expect(Array.from(new Uint8Array(result))).toEqual(Array.from(bytes));
    expect(calls[0]!.url).toContain('/artifacts/artifact%2Fid');
  });

  it('reloads persisted extended runs for a report', async () => {
    const { client, calls } = clientWith(
      new Response('[]', { headers: { 'content-type': 'application/json' } }),
    );

    const runs = await client.deliverability.runsForReport('report/id');

    expect(runs).toEqual([]);
    expect(calls[0]!.url).toContain('/reports/report%2Fid/runs');
  });
});
