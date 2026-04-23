"""Deterministic pool of sandbox phone numbers available for search and purchase.

The pool is loaded lazily on first access and shared across all providers so
that the same E.164 number is never returned to two providers simultaneously
(unless a provider releases it back to the pool).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock


@dataclass(slots=True, frozen=True)
class AvailableNumber:
    """A single available phone number entry."""

    e164: str
    iso_country: str
    number_type: str  # local | mobile | tollfree
    area_code: str
    locality: str
    region: str
    capabilities: dict[str, bool] = field(default_factory=dict)


_pool: list[AvailableNumber] = []
_consumed: set[str] = set()
_lock = RLock()


# US local numbers: 50 per area code for a handful of area codes
_US_LOCAL_AREAS: tuple[tuple[str, str, str], ...] = (
    ("415", "San Francisco", "CA"),
    ("212", "New York", "NY"),
    ("305", "Miami", "FL"),
    ("312", "Chicago", "IL"),
    ("206", "Seattle", "WA"),
)
_US_MOBILE_AREAS: tuple[tuple[str, str, str], ...] = (
    ("917", "New York", "NY"),
    ("650", "San Jose", "CA"),
)
_US_TOLLFREE: tuple[str, ...] = ("800", "833", "844", "855", "866", "877", "888")


def _build_pool() -> list[AvailableNumber]:
    numbers: list[AvailableNumber] = []
    local_caps = {"voice": True, "sms": True, "mms": True, "fax": True}
    mobile_caps = {"voice": True, "sms": True, "mms": True, "fax": False}
    tollfree_caps = {"voice": True, "sms": True, "mms": False, "fax": False}

    # US local — 50 per area code
    for area, locality, region in _US_LOCAL_AREAS:
        for idx in range(50):
            subscriber = 5550000 + idx
            numbers.append(
                AvailableNumber(
                    e164=f"+1{area}{subscriber}",
                    iso_country="US",
                    number_type="local",
                    area_code=area,
                    locality=locality,
                    region=region,
                    capabilities=dict(local_caps),
                )
            )

    # US mobile — 20 per mobile-area-code
    for area, locality, region in _US_MOBILE_AREAS:
        for idx in range(20):
            subscriber = 5554000 + idx
            numbers.append(
                AvailableNumber(
                    e164=f"+1{area}{subscriber}",
                    iso_country="US",
                    number_type="mobile",
                    area_code=area,
                    locality=locality,
                    region=region,
                    capabilities=dict(mobile_caps),
                )
            )

    # US tollfree — 10 per area-code
    for area in _US_TOLLFREE:
        for idx in range(10):
            subscriber = 5550100 + idx
            numbers.append(
                AvailableNumber(
                    e164=f"+1{area}{subscriber}",
                    iso_country="US",
                    number_type="tollfree",
                    area_code=area,
                    locality="Toll Free",
                    region="US",
                    capabilities=dict(tollfree_caps),
                )
            )

    # CA local — 50 for +1416
    for idx in range(50):
        subscriber = 5550000 + idx
        numbers.append(
            AvailableNumber(
                e164=f"+1416{subscriber}",
                iso_country="CA",
                number_type="local",
                area_code="416",
                locality="Toronto",
                region="ON",
                capabilities=dict(local_caps),
            )
        )

    # GB local — 40 under +4420
    for idx in range(40):
        subscriber = 30000000 + idx
        numbers.append(
            AvailableNumber(
                e164=f"+4420{subscriber}",
                iso_country="GB",
                number_type="local",
                area_code="20",
                locality="London",
                region="England",
                capabilities=dict(local_caps),
            )
        )

    return numbers


def _ensure_pool() -> None:
    if not _pool:
        with _lock:
            if not _pool:
                _pool.extend(_build_pool())


def get_available_numbers(
    *,
    iso_country: str = "US",
    number_type: str | None = None,
    area_code: str | None = None,
    contains: str | None = None,
    page_size: int = 50,
    sms_enabled: bool | None = None,
    mms_enabled: bool | None = None,
    voice_enabled: bool | None = None,
) -> list[AvailableNumber]:
    """Return a filtered slice of the available-number pool.

    Numbers already consumed by a provider purchase are excluded until released.
    """
    _ensure_pool()
    with _lock:
        results: list[AvailableNumber] = []
        for entry in _pool:
            if entry.e164 in _consumed:
                continue
            if entry.iso_country != iso_country:
                continue
            if number_type is not None and entry.number_type != number_type:
                continue
            if area_code is not None and entry.area_code != area_code:
                continue
            if contains is not None and contains not in entry.e164:
                continue
            if sms_enabled is True and not entry.capabilities.get("sms"):
                continue
            if mms_enabled is True and not entry.capabilities.get("mms"):
                continue
            if voice_enabled is True and not entry.capabilities.get("voice"):
                continue
            results.append(entry)
            if len(results) >= page_size:
                break
        return results


def mark_consumed(e164: str) -> bool:
    """Reserve a number against the pool. Returns True if now consumed."""
    _ensure_pool()
    with _lock:
        if e164 in _consumed:
            return False
        # Allow consuming numbers that were seeded; reject unknown numbers
        if not any(n.e164 == e164 for n in _pool):
            # Still permit non-seeded numbers (e.g. ported-in) to be consumed.
            _consumed.add(e164)
            return True
        _consumed.add(e164)
        return True


def release_consumed(e164: str) -> bool:
    """Release a number back to the pool. Returns True if it was consumed."""
    with _lock:
        if e164 not in _consumed:
            return False
        _consumed.discard(e164)
        return True


def reset_pool() -> None:
    """Test helper: clear consumed-set so the pool is fully available again."""
    with _lock:
        _consumed.clear()
