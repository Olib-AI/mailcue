"""Simulated call-state-machine worker.

Drives a ``SandboxCall`` through the ``queued → initiated → ringing →
answered → in-progress → completed`` lifecycle, fetching the application's
answer URL (TwiML/BXML/NCCO/TeXML), executing each action in the parsed IR,
and emitting provider-formatted status callbacks.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from weakref import WeakSet

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import AsyncSessionLocal
from app.sandbox.models import SandboxCall, SandboxProvider
from app.sandbox.voice.interpreter import (
    VoiceAction,
    VoiceActionType,
    VoiceIR,
    parse_bxml,
    parse_ncco,
    parse_plivo_xml,
    parse_texml,
    parse_twiml,
)

logger = logging.getLogger("mailcue.sandbox.voice.worker")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# All times in milliseconds for fine-grained test tuning
RING_MS = _int_env("MAILCUE_SANDBOX_VOICE_RING_MS", 100)
ANSWER_MS = _int_env("MAILCUE_SANDBOX_VOICE_ANSWER_MS", 100)
ACTION_MS = _int_env("MAILCUE_SANDBOX_VOICE_ACTION_MS", 50)
COMPLETE_MS = _int_env("MAILCUE_SANDBOX_VOICE_COMPLETE_MS", 50)


StatusCallback = Callable[[str, SandboxCall, dict[str, Any]], Awaitable[None]]
"""A provider-specific callback invoked on each state transition.

Signature: ``await cb(event_type, call, extra_payload)``.
"""


@dataclass(slots=True)
class VoiceCallEnvelope:
    """A call plus the provider-specific status-callback hook."""

    call_id: str
    provider_type: str
    seed_digits: str
    seed_speech: str
    status_cb: StatusCallback


_background_tasks: WeakSet[asyncio.Task[Any]] = WeakSet()


def start_call(
    *,
    call_id: str,
    provider_type: str,
    seed_digits: str,
    seed_speech: str,
    status_cb: StatusCallback,
) -> None:
    """Schedule the simulated call state-machine (fire-and-forget)."""
    envelope = VoiceCallEnvelope(
        call_id=call_id,
        provider_type=provider_type,
        seed_digits=seed_digits,
        seed_speech=seed_speech,
        status_cb=status_cb,
    )
    task = asyncio.create_task(_drive_call(AsyncSessionLocal, envelope))
    _background_tasks.add(task)


async def _sleep_ms(ms: int) -> None:
    if ms > 0:
        await asyncio.sleep(ms / 1000.0)


async def _drive_call(
    db_factory: async_sessionmaker[Any],
    envelope: VoiceCallEnvelope,
) -> None:
    """Drive the state machine for a single call."""
    try:
        await _emit(db_factory, envelope, "initiated")
        await _sleep_ms(RING_MS)
        await _emit(db_factory, envelope, "ringing")
        await _sleep_ms(ANSWER_MS)

        # Fetch application's answer URL
        answer_url, answer_method = await _load_answer_url(db_factory, envelope.call_id)
        if answer_url is None:
            # No answer URL — call still answers briefly then ends
            await _emit(db_factory, envelope, "answered")
            await _sleep_ms(ACTION_MS)
            await _finish(db_factory, envelope, "completed")
            return

        ir = await _fetch_ir(answer_url, answer_method, envelope)
        await _emit(db_factory, envelope, "answered")
        await _execute_ir(db_factory, envelope, ir)
        await _finish(db_factory, envelope, "completed")
    except Exception:  # pragma: no cover — defensive
        logger.exception("Call %s failed", envelope.call_id)
        try:
            await _finish(db_factory, envelope, "failed")
        except Exception:
            logger.exception("Failed to finish call %s", envelope.call_id)


async def _load_answer_url(
    db_factory: async_sessionmaker[Any], call_id: str
) -> tuple[str | None, str]:
    async with db_factory() as db:
        call = await db.get(SandboxCall, call_id)
        if call is None:
            return None, "POST"
        return call.answer_url, (call.answer_method or "POST").upper()


async def _emit(
    db_factory: async_sessionmaker[Any],
    envelope: VoiceCallEnvelope,
    status: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist status transition + invoke provider callback."""
    async with db_factory() as db:
        call = await db.get(SandboxCall, envelope.call_id)
        if call is None:
            return
        call.status = status
        if status == "answered":
            call.answered_at = datetime.now(UTC)
        if status in {"completed", "failed", "canceled", "busy", "no-answer"}:
            call.ended_at = datetime.now(UTC)
            if call.answered_at is not None:
                call.duration_seconds = max(
                    int((call.ended_at - call.answered_at).total_seconds()), 0
                )
        await db.commit()
        snapshot_call = call
        logger.debug("Call %s → %s", call.id, status)
        await envelope.status_cb(status, snapshot_call, extra or {})


async def _finish(
    db_factory: async_sessionmaker[Any],
    envelope: VoiceCallEnvelope,
    status: str,
) -> None:
    await _sleep_ms(COMPLETE_MS)
    await _emit(db_factory, envelope, status)


async def _fetch_ir(
    url: str,
    method: str,
    envelope: VoiceCallEnvelope,
) -> VoiceIR:
    """Fetch application's answer URL and parse into IR."""
    payload = {
        "CallSid": envelope.call_id,
        "CallStatus": "in-progress",
        "From": "",
        "To": "",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if method == "GET":
                resp = await client.get(url, params=payload)
            else:
                resp = await client.post(url, data=payload)
            body = resp.text
        except Exception as exc:
            logger.warning("Answer URL fetch failed (%s): %s", url, exc)
            return VoiceIR(dialect=_dialect_for(envelope.provider_type), raw="")
    return _parse_for_provider(envelope.provider_type, body)


def _dialect_for(provider_type: str) -> str:
    return {
        "twilio": "twiml",
        "bandwidth": "bxml",
        "plivo": "plivo",
        "telnyx": "texml",
        "vonage": "ncco",
    }.get(provider_type, "twiml")


def _parse_for_provider(provider_type: str, body: str) -> VoiceIR:
    match provider_type:
        case "twilio":
            return parse_twiml(body)
        case "bandwidth":
            return parse_bxml(body)
        case "plivo":
            return parse_plivo_xml(body)
        case "telnyx":
            return parse_texml(body)
        case "vonage":
            return parse_ncco(body)
        case _:
            return VoiceIR(raw=body)


async def _execute_ir(
    db_factory: async_sessionmaker[Any],
    envelope: VoiceCallEnvelope,
    ir: VoiceIR,
) -> None:
    """Execute IR actions linearly, handling redirects/gathers recursively."""
    for action in ir.actions:
        await _record_transcript(db_factory, envelope.call_id, action)
        await _sleep_ms(ACTION_MS)
        match action.type:
            case VoiceActionType.HANGUP:
                return
            case VoiceActionType.REJECT:
                await _emit(db_factory, envelope, "canceled")
                return
            case VoiceActionType.REDIRECT | VoiceActionType.GATHER:
                follow_url = action.action_url or action.url
                follow_method = action.action_method or action.method
                if follow_url:
                    # For Gather, send Digits/SpeechResult; for Redirect, no extras
                    followup_payload: dict[str, Any] = {
                        "CallSid": envelope.call_id,
                    }
                    if action.type == VoiceActionType.GATHER:
                        if envelope.seed_digits:
                            followup_payload["Digits"] = envelope.seed_digits
                        if envelope.seed_speech and "speech" in action.input_types:
                            followup_payload["SpeechResult"] = envelope.seed_speech
                    body = await _fetch_raw(follow_url, follow_method, followup_payload)
                    next_ir = _parse_for_provider(envelope.provider_type, body)
                    await _execute_ir(db_factory, envelope, next_ir)
                    return
            case VoiceActionType.RECORD:
                # Simulate record completion and POST to action_url
                if action.action_url:
                    record_payload: dict[str, Any] = {
                        "CallSid": envelope.call_id,
                        "RecordingSid": f"RE{envelope.call_id.replace('-', '')[:32]}",
                        "RecordingDuration": "3",
                        "RecordingUrl": f"https://sandbox.mailcue.local/recordings/{envelope.call_id}",
                    }
                    body = await _fetch_raw(
                        action.action_url, action.action_method, record_payload
                    )
                    next_ir = _parse_for_provider(envelope.provider_type, body)
                    await _execute_ir(db_factory, envelope, next_ir)
                    return
            case VoiceActionType.DIAL:
                # Transient "connect" status
                await _emit(
                    db_factory,
                    envelope,
                    "dialing",
                    {"dial_to": action.dial_to},
                )
            case _:
                continue


async def _fetch_raw(url: str, method: str, payload: dict[str, Any]) -> str:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if method.upper() == "GET":
                resp = await client.get(url, params=payload)
            else:
                resp = await client.post(url, data=payload)
            return resp.text
        except Exception as exc:
            logger.warning("Follow-up fetch failed (%s): %s", url, exc)
            return ""


async def _record_transcript(
    db_factory: async_sessionmaker[Any], call_id: str, action: VoiceAction
) -> None:
    async with db_factory() as db:
        call = await db.get(SandboxCall, call_id)
        if call is None:
            return
        entry = {
            "type": action.type.value,
            "text": action.text,
            "url": action.url,
            "dial_to": action.dial_to,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        transcript = list(call.transcript_json)
        transcript.append(entry)
        call.transcript_json = transcript
        await db.commit()


async def resolve_provider_by_id(
    db_factory: async_sessionmaker[Any], provider_id: str
) -> SandboxProvider | None:
    async with db_factory() as db:
        stmt = select(SandboxProvider).where(SandboxProvider.id == provider_id)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()
