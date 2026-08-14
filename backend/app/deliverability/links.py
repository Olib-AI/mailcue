"""SSRF-resistant, bounded validation of HTTP links found in email HTML."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from contextlib import suppress
from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import settings
from app.emails.schemas import (
    DeliverabilityCategory,
    DeliverabilityCheck,
    DeliverabilityEvidence,
)

_MAX_LINKS = 25


def _display_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path[:300], "", ""))[:500]


def _extract_links(raw: bytes) -> list[str]:
    parsed = message_from_bytes(raw, policy=policy.default)
    if not isinstance(parsed, EmailMessage):
        return []
    links: list[str] = []
    for part in parsed.walk():
        if (
            part.get_content_type() != "text/html"
            or part.get_content_disposition() == "attachment"
        ):
            continue
        with suppress(LookupError, UnicodeError):
            body = str(part.get_content())
            from app.emails.deliverability import _ContentInspector

            inspector = _ContentInspector()
            inspector.feed(body[:2_000_000])
            links.extend(inspector.links)
    return list(dict.fromkeys(links))[:_MAX_LINKS]


async def _public_addresses(host: str, port: int) -> list[str]:
    try:
        resolved = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
            ),
            timeout=settings.deliverability_network_timeout_seconds,
        )
    except (OSError, TimeoutError):
        return []
    addresses = list(dict.fromkeys(entry[4][0] for entry in resolved))
    if not addresses:
        return []
    try:
        parsed = [ipaddress.ip_address(address) for address in addresses]
    except ValueError:
        return []
    if not all(address.is_global for address in parsed):
        return []
    return [str(address) for address in parsed]


async def _probe(client: httpx.AsyncClient, url: str) -> DeliverabilityEvidence:
    parsed = urlsplit(url)
    host = parsed.hostname
    scheme = parsed.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
    ):
        return DeliverabilityEvidence(
            code="unsupported",
            title=_display_url(url),
            value="not_checked",
            description="Only credential-free HTTP and HTTPS links are checked.",
        )
    port = parsed.port or (443 if scheme == "https" else 80)
    if port not in {80, 443}:
        return DeliverabilityEvidence(
            code="blocked_port",
            title=_display_url(url),
            value="not_checked",
            description="The destination uses a port outside the allowed web ports.",
        )
    addresses = await _public_addresses(host, port)
    if not addresses:
        return DeliverabilityEvidence(
            code="unsafe_or_unresolved",
            title=_display_url(url),
            value="not_checked",
            description="The host did not resolve exclusively to globally routable addresses.",
        )

    address = addresses[0]
    netloc = f"[{address}]" if ":" in address else address
    if port != (443 if scheme == "https" else 80):
        netloc = f"{netloc}:{port}"
    pinned_url = urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))
    host_header = host if port in {80, 443} else f"{host}:{port}"
    try:
        response = await client.request(
            "HEAD",
            pinned_url,
            headers={"Host": host_header, "Accept": "*/*"},
            extensions={"sni_hostname": host},
        )
        if response.status_code in {405, 501}:
            async with client.stream(
                "GET",
                pinned_url,
                headers={"Host": host_header, "Range": "bytes=0-0", "Accept": "*/*"},
                extensions={"sni_hostname": host},
            ) as streamed:
                status_code = streamed.status_code
        else:
            status_code = response.status_code
    except (httpx.HTTPError, OSError):
        return DeliverabilityEvidence(
            code="connection_error",
            title=_display_url(url),
            value="error",
            description="The public destination could not be reached within the check budget.",
        )
    if 200 <= status_code < 400:
        code = "redirect" if status_code >= 300 else "ok"
        description = (
            "The destination responds with a redirect. Redirects are not followed."
            if status_code >= 300
            else "The destination responded successfully."
        )
    else:
        code = "http_error"
        description = "The destination returned an error status."
    return DeliverabilityEvidence(
        code=code,
        title=_display_url(url),
        value=status_code,
        description=description,
    )


async def analyze_links(raw: bytes) -> DeliverabilityCategory:
    links = _extract_links(raw)
    if not links:
        check = DeliverabilityCheck(
            id="link_validation",
            category="links",
            title="Live link validation",
            status="info",
            summary="No HTTP or HTTPS links were available for live validation.",
            points=0,
            max_points=0,
        )
        return DeliverabilityCategory(
            id="links", title="Live links", score=None, points=0, max_points=0, checks=[check]
        )
    timeout = httpx.Timeout(settings.deliverability_network_timeout_seconds)
    limits = httpx.Limits(
        max_connections=settings.deliverability_network_concurrency,
        max_keepalive_connections=0,
    )
    semaphore = asyncio.Semaphore(settings.deliverability_network_concurrency)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        limits=limits,
    ) as client:

        async def bounded(url: str) -> DeliverabilityEvidence:
            async with semaphore:
                return await _probe(client, url)

        evidence = await asyncio.gather(*(bounded(url) for url in links))
    successes = sum(item.code in {"ok", "redirect"} for item in evidence)
    failures = sum(item.code in {"http_error", "connection_error"} for item in evidence)
    checked = successes + failures
    points = round(4 * successes / checked, 1) if checked else 0
    status: Literal["pass", "warning", "fail", "info"]
    if failures:
        status = "warning"
        summary = f"{failures} of {checked} checked link(s) failed."
    elif checked:
        status = "pass"
        summary = f"All {checked} checked link(s) responded."
    else:
        status = "info"
        summary = "Links were found, but none met the safe public-destination requirements."
    check = DeliverabilityCheck(
        id="link_validation",
        category="links",
        title="Live link validation",
        status=status,
        summary=summary,
        points=points,
        max_points=4 if checked else 0,
        evidence=evidence,
        recommendation="Repair or remove destinations that return errors." if failures else None,
    )
    score = round(points / 4 * 100) if checked else None
    return DeliverabilityCategory(
        id="links",
        title="Live links",
        score=score,
        points=points,
        max_points=4 if checked else 0,
        checks=[check],
    )
