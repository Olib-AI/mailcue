import { Mailcue, AuthenticationError, MailcueError } from '../node/dist/index.js';

const API_KEY = process.env.MAILCUE_API_KEY;
const BASE_URL = process.env.MAILCUE_BASE_URL || 'http://localhost:8088';
if (!API_KEY) { console.error('MAILCUE_API_KEY not set'); process.exit(1); }

const PASS = '\x1b[32m✓\x1b[0m';
const FAIL = '\x1b[31m✗\x1b[0m';
const results = [];

async function step(name, fn) {
  const t0 = Date.now();
  try {
    const out = await fn();
    const dt = Date.now() - t0;
    results.push({ name, ok: true, info: `${dt}ms` });
    console.log(`  ${PASS} ${name} (${dt}ms)`);
    return out;
  } catch (e) {
    const dt = Date.now() - t0;
    results.push({ name, ok: false, info: `${e.constructor.name}: ${e.message}` });
    console.log(`  ${FAIL} ${name} (${dt}ms) — ${e.constructor.name}: ${e.message}`);
    throw e;
  }
}

const mc = new Mailcue({ apiKey: API_KEY, baseUrl: BASE_URL });

console.log('=== Node SDK ===');

const username = `sdk-node-${Math.random().toString(36).slice(2, 10)}`;
const addr = `${username}@mailcue.local`;
let uid;

try {
  await step('system.health', () => mc.system.health());
  await step('mailboxes.create', () => mc.mailboxes.create({ username, password: 'testpass123', domain: 'mailcue.local' }));
  await step('emails.inject', () => mc.emails.inject({
    mailbox: addr,
    from: 'sender@example.com',
    to: [addr],
    subject: 'Node E2E inject',
    htmlBody: '<h1>From Node SDK</h1>',
  }));
  const list = await step('emails.list', () => mc.emails.list({ mailbox: addr }));
  if (!list.total || list.total < 1) throw new Error(`expected >=1 emails, got ${list.total}`);
  uid = list.emails[0].uid;
  await step('emails.get', () => mc.emails.get(uid, { mailbox: addr }));
  const raw = await step('emails.getRaw', () => mc.emails.getRaw(uid, { mailbox: addr }));
  if (!(raw instanceof ArrayBuffer) || raw.byteLength === 0) throw new Error('expected non-empty ArrayBuffer');
  await step('emails.delete', () => mc.emails.delete(uid, { mailbox: addr }));
  await step('emails.bulkInject', async () => {
    const items = Array.from({ length: 3 }, (_, i) => ({
      mailbox: addr,
      from: `bulk-${i}@example.com`,
      to: [addr],
      subject: `Bulk #${i}`,
      htmlBody: '<p>bulk</p>',
    }));
    const r = await mc.emails.bulkInject(items);
    if (r.injected !== 3) throw new Error(`expected 3 injected, got ${r.injected}`);
  });
  await step('emails.send (SMTP)', () => mc.emails.send({
    from: addr,
    to: [addr],
    subject: 'Node E2E send',
    html: '<b>hello from node</b>',
  }));
  await step('apiKeys.list', () => mc.apiKeys.list());
  await step('auth: 401 on bad key', async () => {
    const bad = new Mailcue({ apiKey: 'mc_invalid_xxx', baseUrl: BASE_URL });
    try {
      await bad.mailboxes.list();
    } catch (e) {
      if (!(e instanceof AuthenticationError)) {
        throw new Error(`expected AuthenticationError, got ${e.constructor.name}`);
      }
      return;
    }
    throw new Error('expected exception');
  });
  await step('mailboxes.delete', () => mc.mailboxes.delete(addr));
} catch {
  // Continue to SSE test even if something failed above.
}

// SSE: open stream, trigger an event from a parallel task
console.log('  ... SSE: opening stream and triggering event');
const sseAddr = 'admin@mailcue.local';
const ac = new AbortController();
let gotEvent = false;
let gotType = null;
const timer = setTimeout(() => ac.abort(), 10000);

const trigger = (async () => {
  await new Promise(r => setTimeout(r, 500));
  try {
    await mc.emails.inject({
      mailbox: sseAddr,
      from: 'sse-trigger-node@example.com',
      to: [sseAddr],
      subject: 'SSE node trigger',
      htmlBody: '<p>trigger</p>',
    });
  } catch (e) {
    console.log(`    trigger error: ${e.message}`);
  }
})();

try {
  for await (const ev of mc.events.stream({ signal: ac.signal })) {
    gotEvent = true;
    gotType = ev.type;
    break;
  }
} catch (e) {
  if (!ac.signal.aborted) console.log(`    SSE error: ${e.message}`);
}
clearTimeout(timer);
ac.abort();
await trigger.catch(() => {});

results.push({ name: 'events.stream', ok: gotEvent, info: gotEvent ? `got ${gotType}` : 'no event in 10s' });
console.log(`  ${gotEvent ? PASS : FAIL} events.stream — ${gotEvent ? 'got ' + gotType : 'NO event in 10s'}`);

console.log();
const passed = results.filter(r => r.ok).length;
console.log(`=== Node: ${passed}/${results.length} passed ===`);
if (passed < results.length) {
  console.log('Failures:');
  for (const r of results) if (!r.ok) console.log(`  - ${r.name}: ${r.info}`);
}
process.exit(passed === results.length ? 0 : 1);
