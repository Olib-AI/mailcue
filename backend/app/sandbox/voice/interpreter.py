"""Normalize TwiML / BXML / TeXML / NCCO voice-control dialects to a common IR.

The simulated call-state machine operates on the IR exclusively. Each provider
emulator receives the application's response (XML/JSON, matching the provider's
wire protocol), parses it into an ``VoiceIR`` object, and executes the
actions in order, emitting provider-formatted webhook events back to the
application at each state transition.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from xml.etree import ElementTree as ET

logger = logging.getLogger("mailcue.sandbox.voice")


class VoiceActionType(str, Enum):
    """The set of call-control verbs supported by the sandbox."""

    SAY = "say"  # Text-to-speech (Say / SpeakSentence / talk / Speak)
    PLAY = "play"  # Play a media URL
    GATHER = "gather"  # Collect DTMF / speech (Gather / GetDigits / input)
    RECORD = "record"  # Record caller audio
    PAUSE = "pause"  # Sleep
    HANGUP = "hangup"  # Terminate the call
    REDIRECT = "redirect"  # Jump to a new URL
    DIAL = "dial"  # Dial another party (Dial / connect)
    REJECT = "reject"  # Reject the call
    CONVERSATION = "conversation"  # Join a multi-party conversation


@dataclass(slots=True)
class VoiceAction:
    """A single call-control step."""

    type: VoiceActionType
    text: str | None = None
    url: str | None = None  # media URL or redirect target
    method: str = "POST"
    timeout: int = 5
    num_digits: int | None = None
    finish_on_key: str | None = None
    action_url: str | None = None  # Gather/Record follow-up
    action_method: str = "POST"
    max_length: int | None = None  # Record
    play_beep: bool = True  # Record
    voice: str | None = None  # Say voice
    language: str | None = None  # Say language
    loop: int = 1
    dial_number: str | None = None
    dial_to: str | None = None
    input_types: list[str] = field(default_factory=lambda: ["dtmf"])
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VoiceIR:
    """A sequence of voice actions to execute on a call."""

    actions: list[VoiceAction] = field(default_factory=list)
    dialect: str = "twiml"  # twiml | bxml | texml | ncco | plivo
    raw: str = ""


# ────────────────────────────────────────────────────────────────────────────
# TwiML parser (Twilio)
# ────────────────────────────────────────────────────────────────────────────


def parse_twiml(body: str) -> VoiceIR:
    """Parse a TwiML <Response> document into a VoiceIR."""
    ir = VoiceIR(dialect="twiml", raw=body)
    try:
        root = ET.fromstring(body.strip())
    except ET.ParseError as exc:
        logger.warning("TwiML parse error: %s", exc)
        return ir

    if root.tag.lower() != "response":
        return ir

    for child in root:
        tag = child.tag.lower()
        text = (child.text or "").strip()
        attrs = {k.lower(): v for k, v in child.attrib.items()}
        match tag:
            case "say":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.SAY,
                        text=text,
                        voice=attrs.get("voice"),
                        language=attrs.get("language"),
                        loop=int(attrs.get("loop", 1)),
                    )
                )
            case "play":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.PLAY,
                        url=text or None,
                        loop=int(attrs.get("loop", 1)),
                    )
                )
            case "pause":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.PAUSE,
                        timeout=int(attrs.get("length", 1)),
                    )
                )
            case "hangup":
                ir.actions.append(VoiceAction(type=VoiceActionType.HANGUP))
            case "reject":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.REJECT,
                        extra={"reason": attrs.get("reason", "rejected")},
                    )
                )
            case "redirect":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.REDIRECT,
                        url=text or attrs.get("url"),
                        method=attrs.get("method", "POST").upper(),
                    )
                )
            case "gather":
                input_types_raw = attrs.get("input", "dtmf")
                gather_children_text: list[str] = []
                for sub in child:
                    sub_text = (sub.text or "").strip()
                    if sub_text:
                        gather_children_text.append(sub_text)
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.GATHER,
                        text=" ".join(gather_children_text) or None,
                        action_url=attrs.get("action"),
                        action_method=attrs.get("method", "POST").upper(),
                        timeout=int(attrs.get("timeout", 5)),
                        num_digits=(int(attrs["numdigits"]) if "numdigits" in attrs else None),
                        finish_on_key=attrs.get("finishonkey", "#"),
                        input_types=[s.strip() for s in input_types_raw.split()],
                    )
                )
            case "record":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.RECORD,
                        action_url=attrs.get("action"),
                        action_method=attrs.get("method", "POST").upper(),
                        max_length=int(attrs.get("maxlength", 3600)),
                        play_beep=(attrs.get("playbeep", "true").lower() == "true"),
                        finish_on_key=attrs.get("finishonkey", "1234567890*#"),
                    )
                )
            case "dial":
                inner_number: str | None = None
                for sub in child:
                    if sub.tag.lower() == "number":
                        inner_number = (sub.text or "").strip() or None
                dial_to = text or inner_number
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.DIAL,
                        dial_to=dial_to,
                        dial_number=dial_to,
                        action_url=attrs.get("action"),
                        timeout=int(attrs.get("timeout", 30)),
                    )
                )
            case _:
                # Unrecognised verb — ignore silently to match Twilio's behavior
                continue

    return ir


# ────────────────────────────────────────────────────────────────────────────
# BXML parser (Bandwidth)
# ────────────────────────────────────────────────────────────────────────────


def parse_bxml(body: str) -> VoiceIR:
    """Parse a Bandwidth BXML ``<Response>`` document."""
    ir = VoiceIR(dialect="bxml", raw=body)
    try:
        root = ET.fromstring(body.strip())
    except ET.ParseError as exc:
        logger.warning("BXML parse error: %s", exc)
        return ir

    if root.tag.lower() != "response":
        return ir

    for child in root:
        tag = child.tag.lower()
        text = (child.text or "").strip()
        attrs = {k.lower(): v for k, v in child.attrib.items()}
        match tag:
            case "speaksentence":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.SAY,
                        text=text,
                        voice=attrs.get("voice"),
                        language=attrs.get("locale"),
                    )
                )
            case "playaudio":
                ir.actions.append(VoiceAction(type=VoiceActionType.PLAY, url=text or None))
            case "pause":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.PAUSE,
                        timeout=int(float(attrs.get("duration", "1"))),
                    )
                )
            case "hangup":
                ir.actions.append(VoiceAction(type=VoiceActionType.HANGUP))
            case "redirect":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.REDIRECT,
                        url=attrs.get("redirecturl"),
                        method=attrs.get("redirectmethod", "POST").upper(),
                    )
                )
            case "gather":
                # Child <SpeakSentence> or <PlayAudio> inside Gather
                prompt_texts: list[str] = []
                for sub in child:
                    if (sub.text or "").strip():
                        prompt_texts.append((sub.text or "").strip())
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.GATHER,
                        text=" ".join(prompt_texts) or None,
                        action_url=attrs.get("gatherurl"),
                        action_method=attrs.get("gathermethod", "POST").upper(),
                        timeout=int(attrs.get("firstdigittimeout", 5)),
                        num_digits=(int(attrs["maxdigits"]) if "maxdigits" in attrs else None),
                        finish_on_key=attrs.get("terminatingdigits", "#"),
                    )
                )
            case "record":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.RECORD,
                        action_url=attrs.get("recordcompleteurl"),
                        action_method=attrs.get("recordcompletemethod", "POST").upper(),
                        max_length=int(attrs.get("maxduration", 300)),
                    )
                )
            case "transfer":
                # <Transfer><PhoneNumber>…</PhoneNumber></Transfer>
                inner_num: str | None = None
                for sub in child:
                    if sub.tag.lower() == "phonenumber":
                        inner_num = (sub.text or "").strip() or None
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.DIAL,
                        dial_to=inner_num,
                        dial_number=inner_num,
                        action_url=attrs.get("transfercompleteurl"),
                    )
                )
            case _:
                continue

    return ir


# ────────────────────────────────────────────────────────────────────────────
# Plivo XML parser
# ────────────────────────────────────────────────────────────────────────────


def parse_plivo_xml(body: str) -> VoiceIR:
    """Parse Plivo's XML response document."""
    ir = VoiceIR(dialect="plivo", raw=body)
    try:
        root = ET.fromstring(body.strip())
    except ET.ParseError as exc:
        logger.warning("Plivo XML parse error: %s", exc)
        return ir

    if root.tag.lower() != "response":
        return ir

    for child in root:
        tag = child.tag.lower()
        text = (child.text or "").strip()
        attrs = {k.lower(): v for k, v in child.attrib.items()}
        match tag:
            case "speak":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.SAY,
                        text=text,
                        voice=attrs.get("voice"),
                        language=attrs.get("language"),
                        loop=int(attrs.get("loop", 1)),
                    )
                )
            case "play":
                ir.actions.append(VoiceAction(type=VoiceActionType.PLAY, url=text or None))
            case "wait":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.PAUSE,
                        timeout=int(attrs.get("length", 1)),
                    )
                )
            case "hangup":
                ir.actions.append(VoiceAction(type=VoiceActionType.HANGUP))
            case "redirect":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.REDIRECT,
                        url=text or attrs.get("url"),
                        method=attrs.get("method", "POST").upper(),
                    )
                )
            case "getdigits":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.GATHER,
                        action_url=attrs.get("action"),
                        action_method=attrs.get("method", "POST").upper(),
                        timeout=int(attrs.get("timeout", 5)),
                        num_digits=(int(attrs["numdigits"]) if "numdigits" in attrs else None),
                        finish_on_key=attrs.get("finishonkey", "#"),
                    )
                )
            case "record":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.RECORD,
                        action_url=attrs.get("action"),
                        action_method=attrs.get("method", "POST").upper(),
                        max_length=int(attrs.get("maxlength", 60)),
                        play_beep=(attrs.get("playbeep", "true").lower() == "true"),
                    )
                )
            case "dial":
                inner_num: str | None = None
                for sub in child:
                    if sub.tag.lower() == "number":
                        inner_num = (sub.text or "").strip() or None
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.DIAL,
                        dial_to=inner_num or text or None,
                        dial_number=inner_num or text or None,
                        action_url=attrs.get("action"),
                        timeout=int(attrs.get("timeout", 30)),
                    )
                )
            case _:
                continue

    return ir


# ────────────────────────────────────────────────────────────────────────────
# TeXML parser (Telnyx)
# ────────────────────────────────────────────────────────────────────────────


def parse_texml(body: str) -> VoiceIR:
    """Parse Telnyx TeXML (TwiML-compatible dialect)."""
    ir = parse_twiml(body)
    ir.dialect = "texml"
    return ir


# ────────────────────────────────────────────────────────────────────────────
# NCCO parser (Vonage)
# ────────────────────────────────────────────────────────────────────────────


def parse_ncco(body: str | list[Any]) -> VoiceIR:
    """Parse a Vonage NCCO JSON array."""
    ir = VoiceIR(dialect="ncco", raw=body if isinstance(body, str) else json.dumps(body))
    if isinstance(body, str):
        try:
            data: Any = json.loads(body)
        except json.JSONDecodeError as exc:
            logger.warning("NCCO JSON parse error: %s", exc)
            return ir
    else:
        data = body
    if not isinstance(data, list):
        return ir

    for entry in data:
        if not isinstance(entry, dict):
            continue
        action_name = str(entry.get("action", "")).lower()
        match action_name:
            case "talk":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.SAY,
                        text=str(entry.get("text", "")),
                        voice=entry.get("voiceName") or entry.get("style"),
                        language=entry.get("language"),
                        loop=int(entry.get("loop", 1)),
                    )
                )
            case "stream":
                urls = entry.get("streamUrl") or []
                if isinstance(urls, list) and urls:
                    ir.actions.append(VoiceAction(type=VoiceActionType.PLAY, url=str(urls[0])))
            case "input":
                event_url = entry.get("eventUrl") or []
                action_url = (
                    str(event_url[0]) if isinstance(event_url, list) and event_url else None
                )
                dtmf = entry.get("dtmf") or {}
                input_types_raw = entry.get("type") or ["dtmf"]
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.GATHER,
                        action_url=action_url,
                        action_method=str(entry.get("eventMethod", "POST")).upper(),
                        timeout=int(dtmf.get("timeOut", 5)) if isinstance(dtmf, dict) else 5,
                        num_digits=(
                            int(dtmf["maxDigits"])
                            if isinstance(dtmf, dict) and "maxDigits" in dtmf
                            else None
                        ),
                        finish_on_key=(
                            str(dtmf.get("submitOnHash", False))
                            if isinstance(dtmf, dict)
                            else None
                        ),
                        input_types=[str(t) for t in input_types_raw]
                        if isinstance(input_types_raw, list)
                        else ["dtmf"],
                    )
                )
            case "record":
                event_url = entry.get("eventUrl") or []
                action_url = (
                    str(event_url[0]) if isinstance(event_url, list) and event_url else None
                )
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.RECORD,
                        action_url=action_url,
                        action_method=str(entry.get("eventMethod", "POST")).upper(),
                        max_length=int(entry.get("endOnSilence", 3))
                        if "endOnSilence" in entry
                        else int(entry.get("endOnKey", 3600) if entry.get("endOnKey") else 3600),
                        play_beep=bool(entry.get("beepStart", True)),
                    )
                )
            case "connect":
                endpoints = entry.get("endpoint") or []
                dial_to = None
                if isinstance(endpoints, list) and endpoints:
                    dial_to = (
                        endpoints[0].get("number") if isinstance(endpoints[0], dict) else None
                    )
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.DIAL,
                        dial_to=dial_to,
                        dial_number=dial_to,
                        timeout=int(entry.get("timeout", 30)),
                    )
                )
            case "conversation":
                ir.actions.append(
                    VoiceAction(
                        type=VoiceActionType.CONVERSATION,
                        extra={"name": str(entry.get("name", ""))},
                    )
                )
            case _:
                continue

    return ir
