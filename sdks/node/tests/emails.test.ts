import { describe, expect, it } from 'vitest';
import { Mailcue } from '../src/index.js';

interface RecordedCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

function makeRecorder(response: () => Response): {
  fetch: typeof fetch;
  calls: RecordedCall[];
} {
  const calls: RecordedCall[] = [];
  const fakeFetch = (async (url: string, init?: RequestInit) => {
    const headers: Record<string, string> = {};
    new Headers(init?.headers as HeadersInit).forEach((v, k) => {
      headers[k] = v;
    });
    let body: unknown = undefined;
    if (init?.body != null) {
      const raw = init.body as string;
      try {
        body = JSON.parse(raw);
      } catch {
        body = raw;
      }
    }
    calls.push({ url, method: init?.method ?? 'GET', headers, body });
    return response();
  }) as unknown as typeof fetch;
  return { fetch: fakeFetch, calls };
}

describe('emails resource', () => {
  it('sends an email and snake_cases fields, base64-encodes attachments', async () => {
    const { fetch: f, calls } = makeRecorder(
      () =>
        new Response(
          JSON.stringify({ message: 'Email accepted for delivery', message_id: '<abc@example.com>' }),
          { status: 202, headers: { 'content-type': 'application/json' } },
        ),
    );

    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f });
    const res = await mc.emails.send({
      from: 'hello@example.com',
      fromName: 'Hello',
      to: ['user@example.com'],
      cc: ['cc@example.com'],
      subject: 'Welcome',
      html: '<h1>Hi</h1>',
      replyTo: 'reply@example.com',
      attachments: [
        {
          filename: 'invoice.pdf',
          contentType: 'application/pdf',
          content: Buffer.from('PDF-DATA'),
        },
      ],
    });
    expect(res.messageId).toBe('<abc@example.com>');
    expect(calls).toHaveLength(1);
    const call = calls[0]!;
    expect(call.url).toBe('http://localhost:8088/api/v1/emails/send');
    expect(call.method).toBe('POST');
    const body = call.body as Record<string, unknown>;
    expect(body['from_address']).toBe('hello@example.com');
    expect(body['from_name']).toBe('Hello');
    expect(body['to_addresses']).toEqual(['user@example.com']);
    expect(body['cc_addresses']).toEqual(['cc@example.com']);
    expect(body['body']).toBe('<h1>Hi</h1>');
    expect(body['body_type']).toBe('html');
    expect(body['reply_to']).toBe('reply@example.com');
    const attachments = body['attachments'] as Array<Record<string, string>>;
    expect(attachments).toHaveLength(1);
    expect(attachments[0]!['filename']).toBe('invoice.pdf');
    expect(attachments[0]!['content_type']).toBe('application/pdf');
    expect(attachments[0]!['data']).toBe(Buffer.from('PDF-DATA').toString('base64'));
  });

  it('lists emails with query params and camelizes the response', async () => {
    const { fetch: f, calls } = makeRecorder(
      () =>
        new Response(
          JSON.stringify({
            total: 1,
            page: 1,
            page_size: 25,
            has_more: false,
            emails: [
              {
                uid: '12',
                mailbox: 'a@b.com',
                from_address: 'x@y.com',
                to_addresses: ['a@b.com'],
                subject: 'hi',
                date: null,
                has_attachments: false,
                is_read: false,
                preview: 'hello',
                message_id: '<id@x>',
                size: 100,
                is_signed: false,
                is_encrypted: false,
              },
            ],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
    );

    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f });
    const res = await mc.emails.list({
      mailbox: 'a@b.com',
      pageSize: 25,
      page: 1,
      folder: 'INBOX',
    });
    expect(res.pageSize).toBe(25);
    expect(res.hasMore).toBe(false);
    expect(res.emails[0]!.fromAddress).toBe('x@y.com');
    expect(res.emails[0]!.hasAttachments).toBe(false);
    expect(calls[0]!.url).toContain('mailbox=a%40b.com');
    expect(calls[0]!.url).toContain('page_size=25');
    expect(calls[0]!.url).toContain('folder=INBOX');
  });

  it('encodes string attachment content as base64 utf-8', async () => {
    let bodyOut: unknown;
    const f = (async (_url: string, init?: RequestInit) => {
      bodyOut = JSON.parse(init?.body as string);
      return new Response('{"message":"ok","message_id":"<id>"}', {
        status: 202,
        headers: { 'content-type': 'application/json' },
      });
    }) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f });
    await mc.emails.send({
      from: 'a@b.com',
      to: ['c@d.com'],
      subject: 's',
      text: 'hi',
      attachments: [{ filename: 'a.txt', contentType: 'text/plain', content: 'hello' }],
    });
    const body = bodyOut as Record<string, unknown>;
    const atts = body['attachments'] as Array<Record<string, string>>;
    expect(atts[0]!['data']).toBe(Buffer.from('hello', 'utf-8').toString('base64'));
  });
});
