import { MailcueError, NetworkError } from './errors.js';
import { camelize, type Transport } from './transport.js';
import type { MailcueEvent } from './types.js';

export interface StreamOptions {
  signal?: AbortSignal;
  reconnect?: boolean;
  initialBackoffMs?: number;
  maxBackoffMs?: number;
}

interface RawSseEvent {
  event: string;
  data: string;
  id?: string;
  retry?: number;
}

export function* parseSseChunks(text: string): Generator<RawSseEvent> {
  const blocks = text.split(/\r?\n\r?\n/);
  for (const block of blocks) {
    if (!block.trim()) continue;
    const ev = parseSseBlock(block);
    if (ev) yield ev;
  }
}

export function parseSseBlock(block: string): RawSseEvent | null {
  let eventName = 'message';
  const dataLines: string[] = [];
  let id: string | undefined;
  let retry: number | undefined;
  let hasData = false;

  for (const rawLine of block.split(/\r?\n/)) {
    if (!rawLine || rawLine.startsWith(':')) continue;
    const colon = rawLine.indexOf(':');
    let field: string;
    let value: string;
    if (colon === -1) {
      field = rawLine;
      value = '';
    } else {
      field = rawLine.slice(0, colon);
      value = rawLine.slice(colon + 1);
      if (value.startsWith(' ')) value = value.slice(1);
    }
    switch (field) {
      case 'event':
        eventName = value;
        break;
      case 'data':
        dataLines.push(value);
        hasData = true;
        break;
      case 'id':
        id = value;
        break;
      case 'retry': {
        const n = Number(value);
        if (!Number.isNaN(n)) retry = n;
        break;
      }
      default:
        break;
    }
  }

  if (!hasData && eventName === 'message') return null;

  const out: RawSseEvent = { event: eventName, data: dataLines.join('\n') };
  if (id !== undefined) out.id = id;
  if (retry !== undefined) out.retry = retry;
  return out;
}

export class EventsClient {
  constructor(private readonly transport: Transport) {}

  async *stream(options: StreamOptions = {}): AsyncGenerator<MailcueEvent> {
    const reconnect = options.reconnect ?? true;
    const initialBackoff = options.initialBackoffMs ?? 1000;
    const maxBackoff = options.maxBackoffMs ?? 30000;
    let attempt = 0;

    while (true) {
      let res: Response;
      try {
        const streamOpts: { path: string; signal?: AbortSignal } = {
          path: '/api/v1/events/stream',
        };
        if (options.signal) streamOpts.signal = options.signal;
        res = await this.transport.stream(streamOpts);
      } catch (err) {
        if (options.signal?.aborted) return;
        if (!reconnect) throw err;
        await waitBackoff(attempt, initialBackoff, maxBackoff, options.signal);
        attempt++;
        continue;
      }

      try {
        attempt = 0;
        yield* iterateSseResponse(res);
        if (!reconnect) return;
      } catch (err) {
        if (options.signal?.aborted) return;
        if (!reconnect) {
          if (err instanceof MailcueError) throw err;
          throw new NetworkError(
            err instanceof Error ? err.message : 'Stream error',
            err,
          );
        }
        await waitBackoff(attempt, initialBackoff, maxBackoff, options.signal);
        attempt++;
      }

      if (options.signal?.aborted) return;
    }
  }
}

async function* iterateSseResponse(res: Response): AsyncGenerator<MailcueEvent> {
  if (!res.body) {
    throw new NetworkError('SSE response has no body');
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        if (buffer.trim()) {
          const ev = parseSseBlock(buffer);
          buffer = '';
          if (ev) {
            const parsed = toMailcueEvent(ev);
            if (parsed) yield parsed;
          }
        }
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while (
        (idx = findBoundary(buffer)) !== -1
      ) {
        const block = buffer.slice(0, idx);
        const advance = boundaryLength(buffer, idx);
        buffer = buffer.slice(idx + advance);
        const ev = parseSseBlock(block);
        if (!ev) continue;
        const parsed = toMailcueEvent(ev);
        if (parsed) yield parsed;
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // ignore
    }
  }
}

function findBoundary(buffer: string): number {
  const a = buffer.indexOf('\n\n');
  const b = buffer.indexOf('\r\n\r\n');
  if (a === -1) return b;
  if (b === -1) return a;
  return Math.min(a, b);
}

function boundaryLength(buffer: string, idx: number): number {
  return buffer.startsWith('\r\n\r\n', idx) ? 4 : 2;
}

function toMailcueEvent(ev: RawSseEvent): MailcueEvent | null {
  let data: unknown = ev.data;
  if (ev.data) {
    try {
      data = camelize(JSON.parse(ev.data));
    } catch {
      data = ev.data;
    }
  }
  const out: MailcueEvent = { type: ev.event, data };
  if (ev.id !== undefined) out.id = ev.id;
  if (ev.retry !== undefined) out.retry = ev.retry;
  return out;
}

async function waitBackoff(
  attempt: number,
  base: number,
  max: number,
  signal?: AbortSignal,
): Promise<void> {
  const delay = Math.min(max, base * 2 ** attempt);
  const jittered = Math.floor(delay * (1 + (Math.random() * 0.4 - 0.2)));
  await new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const t = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, jittered);
    const onAbort = () => {
      clearTimeout(t);
      reject(signal?.reason);
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}
