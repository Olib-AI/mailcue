"""Disposable email domain checker.

Maintains a set of known temporary or disposable email provider domains.
Loads cached lists if available, falls back to a static list, and provides
an asynchronous task to fetch the latest list from a public GitHub blocklist.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger("mailcue.disposable")

# Hardcoded fallback list of extremely common disposable domains
FALLBACK_DOMAINS = {
    "mailinator.com",
    "yopmail.com",
    "yopmail.net",
    "yopmail.fr",
    "guerrillamail.com",
    "guerrillamail.net",
    "guerrillamail.org",
    "guerrillamail.biz",
    "guerrillamail.co",
    "guerrillamail.info",
    "guerrillamail.me",
    "guerrillamail.mobi",
    "guerrillamail.to",
    "guerrillamailblock.com",
    "10minutemail.com",
    "10minutemail.net",
    "10minutemail.co",
    "10minutemail.co.uk",
    "tempmail.com",
    "tempmail.net",
    "tempmail.co",
    "tempmail.live",
    "tempmail.plus",
    "temp-mail.org",
    "temp-mail.io",
    "temp-mail.ru",
    "trashmail.com",
    "sharklasers.com",
    "getairmail.com",
    "mailnesia.com",
    "maildrop.cc",
    "maildrop.org.ua",
    "dispostable.com",
    "mintemail.com",
    "slipry.net",
    "mytrashmail.com",
    "fakeinbox.com",
    "generator.email",
    "tempmailaddress.com",
    "throwawaymail.com",
    "mailcatch.com",
    "tempail.com",
    "fastmail.wtf",
    "anonaddy.com",
    "anonaddy.me",
    "duck.com",
    "mozmail.com",
    "spam4.me",
    "grr.la",
    "mailnull.com",
    "dropmail.me",
    "10minemail.com",
    "crazymailing.com",
    "boun.cr",
    "mailexpire.com",
    "discard.email",
    "jetable.org",
    "safetymail.info",
    "maildu.de",
    "incognitomail.com",
    "temp-mailbox.com",
    "disposablemail.com",
    "emailondeck.com",
    "burnermail.io",
}

# In-memory storage of all loaded disposable domains
_loaded_domains: set[str] = set(FALLBACK_DOMAINS)

BLOCKLIST_URL = "https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/master/disposable_email_blocklist.conf"


def get_cache_file_path() -> Path:
    """Determine the cache file path, preferring /var/lib/mailcue if writable."""
    try:
        parent = Path(settings.gpg_home).parent
        if parent.exists() and os.access(parent, os.W_OK):
            return parent / "disposable_domains.txt"
    except Exception:
        pass
    return Path("/tmp/mailcue_disposable_domains.txt")


def load_cached_domains() -> None:
    """Load domains from the local cache file, falling back to static list."""
    global _loaded_domains
    cache_path = get_cache_file_path()
    if cache_path.exists():
        try:
            domains = set()
            with open(cache_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        domains.add(line.lower())
            if domains:
                _loaded_domains = domains
                logger.info(
                    "Loaded %d disposable domains from cache %s", len(_loaded_domains), cache_path
                )
                return
        except Exception as exc:
            logger.warning("Failed to load cached disposable domains: %s", exc)

    # Fallback/default if cache fails or doesn't exist
    _loaded_domains = set(FALLBACK_DOMAINS)
    logger.info("Initialized with %d fallback disposable domains", len(_loaded_domains))


async def update_disposable_domains() -> None:
    """Asynchronously fetch the latest disposable domains list and write to cache."""
    cache_path = get_cache_file_path()
    logger.info("Fetching latest disposable email domains list from GitHub...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(BLOCKLIST_URL)
            if response.status_code == 200:
                content = response.text
                fetched_domains = set()
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        fetched_domains.add(line.lower())

                if fetched_domains:
                    # Write to cache file
                    try:
                        os.makedirs(cache_path.parent, exist_ok=True)
                        with open(cache_path, "w", encoding="utf-8") as f:
                            for domain in sorted(fetched_domains):
                                f.write(domain + "\n")
                        global _loaded_domains
                        _loaded_domains = fetched_domains
                        logger.info(
                            "Successfully updated and cached %d disposable domains",
                            len(_loaded_domains),
                        )
                    except Exception as write_exc:
                        logger.error("Failed to write disposable domains cache: %s", write_exc)
            else:
                logger.warning(
                    "Failed to fetch disposable domains from GitHub: HTTP %d", response.status_code
                )
    except Exception as exc:
        logger.warning("Failed to update disposable domains list: %s", exc)


_update_task: asyncio.Task[None] | None = None


def _check_cache_age_and_trigger_update() -> None:
    """Trigger update if the cache file is older than 24 hours."""
    global _update_task
    cache_path = get_cache_file_path()
    if cache_path.exists():
        try:
            mtime = os.path.getmtime(cache_path)
            age_seconds = time.time() - mtime
            # 24 hours = 86400 seconds
            if age_seconds > 86400:
                logger.info(
                    "Disposable domains cache is older than 24 hours. Triggering background update..."
                )
                _update_task = asyncio.create_task(update_disposable_domains())
        except Exception as exc:
            logger.warning("Failed to check cache age: %s", exc)


def is_disposable_domain(domain: str) -> bool:
    """Check if the given domain is in the set of disposable domains."""
    _check_cache_age_and_trigger_update()
    return domain.strip().lower() in _loaded_domains
