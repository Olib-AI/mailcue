import { describe, expect, it } from 'vitest';
import { Mailcue } from '../src/index.js';
import { parseSseBlock, parseSseChunks } from '../src/events.js';

describe('SSE parsing', () => {
  it('parses two events from a fixture', () => {
    const fixture =
      'event: email.received\ndata: {"uid":"1","mailbox":"a@b.com"}\n\n' +
      'event: heartbeat\ndata: \n\n' +
      'event: email.sent\ndata: {"message_id":"<x@y>"}\n\n';
    const events = Array.from(parseSseChunks(fixture));
    expect(events).toHaveLength(3);
    expect(events[0]!.event).toBe('email.received');
    expect(events[0]!.data).toBe('{"uid":"1","mailbox":"a@b.com"}');
    expect(events[1]!.event).toBe('heartbeat');
    expect(events[2]!.event).toBe('email.sent');
  });

  it('parses an event with id and retry', () => {
    const block = 'event: ping\nid: 42\nretry: 5000\ndata: hi\n';
    const ev = parseSseBlock(block);
    expect(ev?.event).toBe('ping');
    expect(ev?.id).toBe('42');
    expect(ev?.retry).toBe(5000);
    expect(ev?.data).toBe('hi');
  });

  it('skips comment lines and ignores blocks without data when event is "message"', () => {
    expect(parseSseBlock(': just a comment')).toBeNull();
  });

  it('streams events from a fetch ReadableStream and camelizes JSON', async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode('event: email.received\ndata: {"message_id":"<id1>","is_read":false}\n\n'),
        );
        controller.enqueue(encoder.encode('event: heartbeat\ndata: \n\n'));
        controller.close();
      },
    });
    const f = (async () =>
      new Response(body, {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      })) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f });
    const collected: Array<{ type: string; data: unknown }> = [];
    for await (const ev of mc.events.stream({ reconnect: false })) {
      collected.push({ type: ev.type, data: ev.data });
      if (collected.length === 2) break;
    }
    expect(collected).toHaveLength(2);
    expect(collected[0]!.type).toBe('email.received');
    const data = collected[0]!.data as Record<string, unknown>;
    expect(data['messageId']).toBe('<id1>');
    expect(data['isRead']).toBe(false);
    expect(collected[1]!.type).toBe('heartbeat');
  });

  it('aborts the stream when the AbortSignal fires before connecting', async () => {
    const f = (async () =>
      new Response('', {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      })) as unknown as typeof fetch;
    const mc = new Mailcue({ apiKey: 'mc_test', fetch: f });
    const ctrl = new AbortController();
    ctrl.abort();
    const collected: unknown[] = [];
    for await (const ev of mc.events.stream({ signal: ctrl.signal, reconnect: false })) {
      collected.push(ev);
    }
    expect(collected).toHaveLength(0);
  });
});
