"""Per-provider sandbox capability advertisement.

Exposes a deterministic capability matrix that fase's adapters can consult
to decide which features to enable when running against the sandbox.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter

CAPABILITIES: Final[dict[str, dict[str, bool]]] = {
    "twilio": {
        "sms": True,
        "mms": True,
        "voice": True,
        "porting": True,
        "tcr": True,
        "number_search": True,
    },
    "bandwidth": {
        "sms": True,
        "mms": True,
        "voice": True,
        "porting": True,
        "tcr": True,
        "number_search": True,
    },
    "vonage": {
        "sms": True,
        "mms": True,
        "voice": True,
        "porting": False,
        "tcr": False,
        "number_search": True,
    },
    "plivo": {
        "sms": True,
        "mms": True,
        "voice": True,
        "porting": True,
        "tcr": True,
        "number_search": True,
    },
    "telnyx": {
        "sms": True,
        "mms": True,
        "voice": True,
        "porting": True,
        "tcr": True,
        "number_search": True,
    },
}


router = APIRouter(prefix="/sandbox/providers", tags=["Sandbox - Capabilities"])


@router.get("/capabilities")
async def get_capabilities() -> dict[str, dict[str, dict[str, bool]]]:
    """Return the sandbox capability matrix keyed by provider name."""
    return {"providers": {k: dict(v) for k, v in CAPABILITIES.items()}}
