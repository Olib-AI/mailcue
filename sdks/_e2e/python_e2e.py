from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
import uuid

from mailcue import AsyncMailcue, Mailcue, MailcueError

API_KEY = os.environ["MAILCUE_API_KEY"]
BASE_URL = os.environ.get("MAILCUE_BASE_URL", "http://localhost:8088")

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
results: list[tuple[str, bool, str]] = []


def step(name: str):
    def decorator(fn):
        def wrapper(*a, **kw):
            t0 = time.time()
            try:
                out = fn(*a, **kw)
                dt = (time.time() - t0) * 1000
                results.append((name, True, f"{dt:.0f}ms"))
                print(f"  {PASS} {name} ({dt:.0f}ms)")
                return out
            except Exception as e:
                dt = (time.time() - t0) * 1000
                results.append((name, False, f"{type(e).__name__}: {e}"))
                print(f"  {FAIL} {name} ({dt:.0f}ms) — {type(e).__name__}: {e}")
                raise

        return wrapper

    return decorator


def main_sync() -> None:
    print("=== Python sync SDK ===")
    mc = Mailcue(api_key=API_KEY, base_url=BASE_URL)

    @step("system.health")
    def t_health():
        h = mc.system.health()
        assert h is not None

    @step("mailboxes.create")
    def t_create_mailbox():
        username = f"sdk-e2e-{uuid.uuid4().hex[:8]}"
        addr = f"{username}@mailcue.local"
        mc.mailboxes.create(username, "testpass123", domain="mailcue.local")
        return addr

    @step("emails.inject")
    def t_inject(mailbox: str):
        r = mc.emails.inject(
            mailbox=mailbox,
            from_address="sender@example.com",
            to_addresses=[mailbox],
            subject="E2E inject test",
            html_body="<h1>From Python SDK</h1>",
        )
        return r

    @step("emails.list")
    def t_list(mailbox: str):
        emails = mc.emails.list(mailbox=mailbox)
        assert emails.total >= 1, f"expected >=1, got {emails.total}"
        return emails.emails[0].uid

    @step("emails.get")
    def t_get(mailbox: str, uid: str):
        e = mc.emails.get(uid, mailbox=mailbox)
        assert e.subject == "E2E inject test"

    @step("emails.get_raw")
    def t_raw(mailbox: str, uid: str):
        raw = mc.emails.get_raw(uid, mailbox=mailbox)
        assert isinstance(raw, bytes) and len(raw) > 0

    @step("emails.delete")
    def t_delete(mailbox: str, uid: str):
        mc.emails.delete(uid, mailbox=mailbox)

    @step("emails.bulk_inject")
    def t_bulk(mailbox: str):
        items = [
            {
                "mailbox": mailbox,
                "from_address": f"bulk-{i}@example.com",
                "to_addresses": [mailbox],
                "subject": f"Bulk #{i}",
                "html_body": "<p>bulk</p>",
            }
            for i in range(3)
        ]
        r = mc.emails.bulk_inject(items)
        assert r.injected == 3

    @step("emails.send (SMTP)")
    def t_send(mailbox: str):
        r = mc.emails.send(
            from_=mailbox,
            to=[mailbox],
            subject="E2E send via SMTP",
            html="<b>hello</b>",
        )
        assert r is not None

    @step("api_keys.list")
    def t_keys():
        keys = mc.api_keys.list()
        assert len(keys) >= 1

    @step("auth: 401 on bad key")
    def t_401():
        bad = Mailcue(api_key="mc_invalid_xxx", base_url=BASE_URL)
        try:
            bad.mailboxes.list()
        except MailcueError as e:
            from mailcue import AuthenticationError

            assert isinstance(e, AuthenticationError), (
                f"expected AuthenticationError, got {type(e).__name__}"
            )
            return
        raise AssertionError("expected exception")

    @step("mailboxes.delete")
    def t_delete_mb(mailbox: str):
        mc.mailboxes.delete(mailbox)

    t_health()
    addr = t_create_mailbox()
    t_inject(addr)
    uid = t_list(addr)
    t_get(addr, uid)
    t_raw(addr, uid)
    t_delete(addr, uid)
    t_bulk(addr)
    t_send(addr)
    time.sleep(1)
    t_keys()
    t_401()
    t_delete_mb(addr)
    mc.close()


async def main_async() -> None:
    print("=== Python async SDK ===")
    async with AsyncMailcue(api_key=API_KEY, base_url=BASE_URL) as mc:

        async def step_async(name, coro):
            t0 = time.time()
            try:
                out = await coro
                dt = (time.time() - t0) * 1000
                results.append((f"async:{name}", True, f"{dt:.0f}ms"))
                print(f"  {PASS} {name} ({dt:.0f}ms)")
                return out
            except Exception as e:
                dt = (time.time() - t0) * 1000
                results.append((f"async:{name}", False, f"{type(e).__name__}: {e}"))
                print(f"  {FAIL} {name} ({dt:.0f}ms) — {type(e).__name__}: {e}")
                raise

        await step_async("system.health", mc.system.health())
        username = f"sdk-async-{uuid.uuid4().hex[:8]}"
        addr = f"{username}@mailcue.local"
        await step_async(
            "mailboxes.create", mc.mailboxes.create(username, "testpass123", domain="mailcue.local")
        )
        await step_async(
            "emails.inject",
            mc.emails.inject(
                mailbox=addr,
                from_address="async@example.com",
                to_addresses=[addr],
                subject="async test",
                html_body="<p>async</p>",
            ),
        )
        listing = await step_async("emails.list", mc.emails.list(mailbox=addr))
        assert listing.total >= 1
        uid = listing.emails[0].uid
        await step_async("emails.get", mc.emails.get(uid, mailbox=addr))
        await step_async("emails.delete", mc.emails.delete(uid, mailbox=addr))
        await step_async("mailboxes.delete", mc.mailboxes.delete(addr))

        # SSE: subscribe, then trigger an event from a parallel task
        print("  ... SSE: opening stream and triggering event")
        sse_addr = "admin@mailcue.local"
        got_event = False
        got_type = None

        async def trigger():
            await asyncio.sleep(0.5)
            await mc.emails.inject(
                mailbox=sse_addr,
                from_address="sse-trigger@example.com",
                to_addresses=[sse_addr],
                subject="SSE async trigger",
                html_body="<p>trigger</p>",
            )

        async def listen():
            nonlocal got_event, got_type
            async for ev in mc.events.stream():
                got_event = True
                got_type = getattr(ev, "type", None) or getattr(ev, "event_type", None) or repr(ev)
                break

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.gather(listen(), trigger()), timeout=10.0)
        results.append(
            (
                "async:events.stream",
                got_event,
                f"got {got_type}" if got_event else "no event in 10s",
            )
        )
        marker = PASS if got_event else FAIL
        print(
            f"  {marker} events.stream — {'got ' + str(got_type) if got_event else 'NO event in 10s'}"
        )


def main() -> int:
    with contextlib.suppress(Exception):
        main_sync()
    with contextlib.suppress(Exception):
        asyncio.run(main_async())
    print()
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"=== Python: {passed}/{total} passed ===")
    if passed < total:
        print("Failures:")
        for name, ok, info in results:
            if not ok:
                print(f"  - {name}: {info}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
