"""Shared DNS resolver for the validation and risk-signal paths.

One resolver instance keeps a single LRU cache in front of every lookup. A
batch of addresses at the same domain is the common case, so the cache removes
almost all repeated queries.
"""

from __future__ import annotations

import asyncio

import dns.resolver

resolver = dns.resolver.Resolver()
resolver.timeout = 1.0
resolver.lifetime = 2.0
resolver.cache = dns.resolver.LRUCache()


async def resolve(name: str, rdtype: str) -> list[object]:
    """Resolve one record type, returning an empty list for absent records."""
    try:
        answers = await asyncio.to_thread(resolver.resolve, name, rdtype)
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
        return []
    except Exception:
        return []
    return list(answers)


async def resolve_txt(name: str) -> list[str]:
    """Resolve TXT records, joining the character strings of each record."""
    records: list[str] = []
    for rdata in await resolve(name, "TXT"):
        strings = getattr(rdata, "strings", None)
        if strings:
            records.append(b"".join(strings).decode("utf-8", errors="replace"))
        else:
            records.append(str(rdata).strip('"'))
    return records
