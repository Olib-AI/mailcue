"""Fire-and-forget webhook delivery for arbitrary provider payloads.

Unlike ``webhook_worker.deliver_webhooks`` which is tied to ``SandboxMessage``,
this module delivers any payload to any URL. Status callbacks for voice,
porting, brand registration, and campaign lifecycle use this path.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any
from weakref import WeakSet

import httpx

logger = logging.getLogger("mailcue.sandbox.webhook_raw")


_LOCALHOST_PORT_RE = re.compile(
    r"^(https?://)(localhost|127\.0\.0\.1):(\d+)(/.*)?$", re.IGNORECASE
)


def _rewrite_localhost_url(url: str) -> str:
    m = _LOCALHOST_PORT_RE.match(url)
    if m:
        scheme, host, _port, path = m.groups()
        return f"{scheme}{host}:80{path or '/'}"
    return url


_background_tasks: WeakSet[asyncio.Task[Any]] = WeakSet()

SigningFn = Callable[[dict[str, str], bytes], Awaitable[dict[str, str]]]


async def post_json(
    url: str,
    payload: dict[str, Any] | list[Any],
    *,
    headers: dict[str, str] | None = None,
    signer: SigningFn | None = None,
    timeout: float = 10.0,
) -> httpx.Response | None:
    """Deliver a JSON payload synchronously (awaitable)."""
    import json as _json

    body = _json.dumps(payload).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "User-Agent": "MailCue-Sandbox/1.0"}
    if headers:
        hdrs.update(headers)
    if signer is not None:
        hdrs = await signer(hdrs, body)
    target = _rewrite_localhost_url(url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            return await client.post(target, content=body, headers=hdrs)
        except Exception as exc:
            logger.warning("Webhook POST failed %s: %s", url, exc)
            return None


async def post_form(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    signer: SigningFn | None = None,
    timeout: float = 10.0,
) -> httpx.Response | None:
    """Deliver a form-encoded payload (used by Twilio status callbacks)."""
    from urllib.parse import urlencode

    body = urlencode({k: str(v) for k, v in payload.items() if v is not None}).encode("utf-8")
    hdrs = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "MailCue-Sandbox/1.0",
    }
    if headers:
        hdrs.update(headers)
    if signer is not None:
        hdrs = await signer(hdrs, body)
    target = _rewrite_localhost_url(url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            return await client.post(target, content=body, headers=hdrs)
        except Exception as exc:
            logger.warning("Webhook POST form failed %s: %s", url, exc)
            return None


async def post_xml(
    url: str,
    xml_body: str,
    *,
    headers: dict[str, str] | None = None,
    signer: SigningFn | None = None,
    timeout: float = 10.0,
) -> httpx.Response | None:
    """Deliver an XML payload (used by Bandwidth webhooks)."""
    body = xml_body.encode("utf-8")
    hdrs = {"Content-Type": "application/xml", "User-Agent": "MailCue-Sandbox/1.0"}
    if headers:
        hdrs.update(headers)
    if signer is not None:
        hdrs = await signer(hdrs, body)
    target = _rewrite_localhost_url(url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            return await client.post(target, content=body, headers=hdrs)
        except Exception as exc:
            logger.warning("Webhook POST xml failed %s: %s", url, exc)
            return None


def fire_and_forget(coro: Awaitable[Any]) -> None:
    """Schedule an awaitable as a background task, retaining a reference."""
    task = asyncio.create_task(coro)  # type: ignore[arg-type]
    _background_tasks.add(task)
