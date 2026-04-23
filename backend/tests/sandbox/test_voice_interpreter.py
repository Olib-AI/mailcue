"""Unit tests for the unified voice interpreter."""

from __future__ import annotations

from app.sandbox.voice.interpreter import (
    VoiceActionType,
    parse_bxml,
    parse_ncco,
    parse_plivo_xml,
    parse_texml,
    parse_twiml,
)

# ── TwiML ────────────────────────────────────────────────────────────


def test_twiml_say_gather_hangup():
    body = """
    <Response>
      <Say voice="alice">Welcome</Say>
      <Gather action="https://app/next" numDigits="1" timeout="5">
        <Say>Press 1</Say>
      </Gather>
      <Hangup/>
    </Response>
    """
    ir = parse_twiml(body)
    assert ir.dialect == "twiml"
    assert len(ir.actions) == 3
    assert ir.actions[0].type == VoiceActionType.SAY
    assert ir.actions[0].text == "Welcome"
    assert ir.actions[0].voice == "alice"
    assert ir.actions[1].type == VoiceActionType.GATHER
    assert ir.actions[1].num_digits == 1
    assert ir.actions[1].action_url == "https://app/next"
    assert ir.actions[2].type == VoiceActionType.HANGUP


def test_twiml_dial_number():
    body = """
    <Response>
      <Dial>+15551234567</Dial>
    </Response>
    """
    ir = parse_twiml(body)
    assert ir.actions[0].type == VoiceActionType.DIAL
    assert ir.actions[0].dial_to == "+15551234567"


def test_twiml_record():
    body = """
    <Response>
      <Record action="https://app/done" maxLength="60" playBeep="true"/>
    </Response>
    """
    ir = parse_twiml(body)
    assert ir.actions[0].type == VoiceActionType.RECORD
    assert ir.actions[0].max_length == 60
    assert ir.actions[0].action_url == "https://app/done"


def test_twiml_invalid_xml_returns_empty_ir():
    ir = parse_twiml("not xml")
    assert ir.actions == []


# ── BXML ────────────────────────────────────────────────────────────


def test_bxml_speak_gather_transfer():
    body = """
    <Response>
      <SpeakSentence voice="bridget" locale="en_US">Hello</SpeakSentence>
      <Gather maxDigits="4" gatherUrl="https://app/gather" firstDigitTimeout="10"/>
      <Transfer transferCompleteUrl="https://app/xfer">
        <PhoneNumber>+15551234567</PhoneNumber>
      </Transfer>
    </Response>
    """
    ir = parse_bxml(body)
    assert ir.dialect == "bxml"
    assert len(ir.actions) == 3
    assert ir.actions[0].type == VoiceActionType.SAY
    assert ir.actions[0].voice == "bridget"
    assert ir.actions[1].type == VoiceActionType.GATHER
    assert ir.actions[1].num_digits == 4
    assert ir.actions[1].action_url == "https://app/gather"
    assert ir.actions[2].type == VoiceActionType.DIAL
    assert ir.actions[2].dial_to == "+15551234567"


def test_bxml_hangup_playaudio():
    body = """
    <Response>
      <PlayAudio>https://example.com/a.wav</PlayAudio>
      <Hangup/>
    </Response>
    """
    ir = parse_bxml(body)
    assert ir.actions[0].type == VoiceActionType.PLAY
    assert ir.actions[0].url == "https://example.com/a.wav"
    assert ir.actions[1].type == VoiceActionType.HANGUP


# ── Plivo ────────────────────────────────────────────────────────────


def test_plivo_speak_getdigits_dial():
    body = """
    <Response>
      <Speak voice="WOMAN" language="en-US">Welcome</Speak>
      <GetDigits action="https://app/digits" numDigits="1" timeout="5"/>
      <Dial><Number>+15559999999</Number></Dial>
    </Response>
    """
    ir = parse_plivo_xml(body)
    assert ir.dialect == "plivo"
    assert len(ir.actions) == 3
    assert ir.actions[0].type == VoiceActionType.SAY
    assert ir.actions[1].type == VoiceActionType.GATHER
    assert ir.actions[1].num_digits == 1
    assert ir.actions[2].type == VoiceActionType.DIAL
    assert ir.actions[2].dial_to == "+15559999999"


def test_plivo_wait_hangup():
    body = """
    <Response>
      <Wait length="3"/>
      <Hangup/>
    </Response>
    """
    ir = parse_plivo_xml(body)
    assert ir.actions[0].type == VoiceActionType.PAUSE
    assert ir.actions[0].timeout == 3
    assert ir.actions[1].type == VoiceActionType.HANGUP


# ── TeXML (Telnyx) ───────────────────────────────────────────────────


def test_texml_matches_twiml_verbs():
    body = """
    <Response>
      <Say>Telnyx</Say>
      <Hangup/>
    </Response>
    """
    ir = parse_texml(body)
    assert ir.dialect == "texml"
    assert ir.actions[0].type == VoiceActionType.SAY
    assert ir.actions[1].type == VoiceActionType.HANGUP


# ── NCCO (Vonage) ────────────────────────────────────────────────────


def test_ncco_talk_input_connect():
    ncco = [
        {"action": "talk", "text": "Welcome to ACME"},
        {
            "action": "input",
            "type": ["dtmf"],
            "dtmf": {"maxDigits": 1, "timeOut": 5},
            "eventUrl": ["https://app/input"],
        },
        {
            "action": "connect",
            "endpoint": [{"type": "phone", "number": "15559876543"}],
            "timeout": 30,
        },
    ]
    ir = parse_ncco(ncco)
    assert ir.dialect == "ncco"
    assert len(ir.actions) == 3
    assert ir.actions[0].type == VoiceActionType.SAY
    assert ir.actions[0].text == "Welcome to ACME"
    assert ir.actions[1].type == VoiceActionType.GATHER
    assert ir.actions[1].num_digits == 1
    assert ir.actions[1].action_url == "https://app/input"
    assert ir.actions[2].type == VoiceActionType.DIAL
    assert ir.actions[2].dial_to == "15559876543"


def test_ncco_record_stream():
    ncco = [
        {"action": "stream", "streamUrl": ["https://example.com/a.mp3"]},
        {"action": "record", "eventUrl": ["https://app/rec"], "beepStart": False},
    ]
    ir = parse_ncco(ncco)
    assert ir.actions[0].type == VoiceActionType.PLAY
    assert ir.actions[0].url == "https://example.com/a.mp3"
    assert ir.actions[1].type == VoiceActionType.RECORD
    assert ir.actions[1].action_url == "https://app/rec"


def test_ncco_invalid_json():
    ir = parse_ncco("not-json")
    assert ir.actions == []


def test_ncco_from_json_string():
    body = '[{"action":"talk","text":"hi"}]'
    ir = parse_ncco(body)
    assert ir.actions[0].type == VoiceActionType.SAY
