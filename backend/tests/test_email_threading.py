"""Email-threading tests — parser header extraction + thread_id derivation.

Covers:
  * ``_parse_message_id_list`` for single-line, folded, and garbage inputs.
  * ``compute_thread_id`` for root, References-bearing reply, and
    In-Reply-To-only reply.
  * Both parser entry points (``parse_email_summary`` + ``parse_email_async``)
    populate ``in_reply_to`` / ``references`` / ``thread_id`` on a synthetic
    raw email.
  * ``list_emails(..., thread_view=True)`` re-sorts the page by
    ``(thread_id, date asc)`` using a stubbed IMAP connection.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.emails import service as email_service
from app.emails.parser import (
    _parse_message_id_list,
    compute_thread_id,
    parse_email_async,
    parse_email_summary,
)

# ── _parse_message_id_list ───────────────────────────────────────


def test_parse_message_id_list_multiple_tokens() -> None:
    """Whitespace-separated tokens are returned in order with brackets kept."""
    raw = "<a@x>  <b@y>\n  <c@z>"
    assert _parse_message_id_list(raw) == ["<a@x>", "<b@y>", "<c@z>"]


def test_parse_message_id_list_garbage_returns_empty() -> None:
    """Free-form text without ``<...>`` tokens yields an empty list."""
    assert _parse_message_id_list("garbage") == []


def test_parse_message_id_list_empty_input() -> None:
    """Empty / falsy input yields an empty list (not None)."""
    assert _parse_message_id_list("") == []


def test_parse_message_id_list_single_line_references() -> None:
    """Classic single-line ``References`` header parses to ordered list."""
    raw = "<root@host.example> <reply1@host.example> <reply2@host.example>"
    assert _parse_message_id_list(raw) == [
        "<root@host.example>",
        "<reply1@host.example>",
        "<reply2@host.example>",
    ]


def test_parse_message_id_list_folded_multiline_references() -> None:
    """RFC 5322 folded ``References`` header (continuation lines indented)."""
    raw = (
        "<root@host.example>\r\n"
        " <reply1@host.example>\r\n"
        "\t<reply2@host.example>\r\n"
        "  <reply3@host.example>"
    )
    assert _parse_message_id_list(raw) == [
        "<root@host.example>",
        "<reply1@host.example>",
        "<reply2@host.example>",
        "<reply3@host.example>",
    ]


# ── compute_thread_id ────────────────────────────────────────────


def test_compute_thread_id_root_message() -> None:
    """A root message threads with itself: thread_id == its own Message-ID."""
    mid = "<root@host.example>"
    assert compute_thread_id(mid, in_reply_to=None, references=[]) == mid


def test_compute_thread_id_reply_with_references() -> None:
    """Reply with non-empty References → first References entry."""
    refs = ["<root@host.example>", "<reply1@host.example>"]
    tid = compute_thread_id(
        "<reply2@host.example>",
        in_reply_to="<reply1@host.example>",
        references=refs,
    )
    assert tid == "<root@host.example>"


def test_compute_thread_id_reply_with_only_in_reply_to() -> None:
    """Reply with In-Reply-To but empty References → the In-Reply-To value."""
    tid = compute_thread_id(
        "<reply2@host.example>",
        in_reply_to="<root@host.example>",
        references=[],
    )
    assert tid == "<root@host.example>"


# ── End-to-end parser entry points ───────────────────────────────


_SYNTHETIC_RAW: bytes = (
    b"From: Alice <alice@example.com>\r\n"
    b"To: Bob <bob@example.com>\r\n"
    b"Subject: Re: hello\r\n"
    b"Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
    b"Message-ID: <reply2@host.example>\r\n"
    b"In-Reply-To: <reply1@host.example>\r\n"
    b"References: <root@host.example>\r\n"
    b" <reply1@host.example>\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: text/plain; charset="utf-8"\r\n'
    b"\r\n"
    b"hi there\r\n"
)


def test_parse_email_summary_populates_threading_fields() -> None:
    """``parse_email_summary`` surfaces in_reply_to / references / thread_id."""
    summary = parse_email_summary(_SYNTHETIC_RAW, uid="42", mailbox="bob@example.com")

    assert summary.message_id == "<reply2@host.example>"
    assert summary.in_reply_to == "<reply1@host.example>"
    assert summary.references == ["<root@host.example>", "<reply1@host.example>"]
    # First References entry by convention is the conversation root.
    assert summary.thread_id == "<root@host.example>"


async def test_parse_email_async_populates_threading_fields() -> None:
    """``parse_email_async`` surfaces in_reply_to / references / thread_id."""
    detail = await parse_email_async(_SYNTHETIC_RAW, uid="42", mailbox="bob@example.com")

    assert detail.message_id == "<reply2@host.example>"
    assert detail.in_reply_to == "<reply1@host.example>"
    assert detail.references == ["<root@host.example>", "<reply1@host.example>"]
    assert detail.thread_id == "<root@host.example>"


# ── list_emails(thread_view=True) ────────────────────────────────


def _build_raw(
    *,
    message_id: str,
    subject: str,
    date_rfc: str,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
) -> bytes:
    """Construct minimal RFC 5322 bytes for the IMAP fake."""
    headers = [
        b"From: Alice <alice@example.com>",
        b"To: Bob <bob@example.com>",
        f"Subject: {subject}".encode(),
        f"Date: {date_rfc}".encode(),
        f"Message-ID: {message_id}".encode(),
    ]
    if in_reply_to:
        headers.append(f"In-Reply-To: {in_reply_to}".encode())
    if references:
        headers.append(f"References: {' '.join(references)}".encode())
    headers.extend(
        [
            b"MIME-Version: 1.0",
            b'Content-Type: text/plain; charset="utf-8"',
            b"",
            b"body",
            b"",
        ]
    )
    return b"\r\n".join(headers)


# Thread A: root + reply.  Thread B: standalone (self-thread).
_FIXTURE_RAW: dict[str, bytes] = {
    "10": _build_raw(  # Thread A root, oldest
        message_id="<a-root@host>",
        subject="Thread A root",
        date_rfc="Mon, 01 Jan 2024 09:00:00 +0000",
    ),
    "11": _build_raw(  # Thread B standalone, mid
        message_id="<b-only@host>",
        subject="Thread B standalone",
        date_rfc="Mon, 01 Jan 2024 10:00:00 +0000",
    ),
    "12": _build_raw(  # Thread A reply, newest
        message_id="<a-reply@host>",
        subject="Re: Thread A root",
        date_rfc="Mon, 01 Jan 2024 11:00:00 +0000",
        in_reply_to="<a-root@host>",
        references=["<a-root@host>"],
    ),
}


class _FakeIMAP:
    """Minimal stand-in for ``aioimaplib.IMAP4`` covering ``list_emails``.

    Implements only the methods used by ``list_emails``: ``select``,
    ``uid_search``, ``uid`` (FETCH), and ``logout``.  The ``uid("fetch", ...)``
    response shape mirrors what ``aioimaplib`` returns: an interleaved list
    of FETCH header lines and raw RFC 822 bytes blocks, terminated by
    closing parens.  ``list_emails`` parses this stream by detecting
    ``"FETCH"`` + ``"UID"`` on each line.
    """

    def __init__(self, raw_by_uid: dict[str, bytes]) -> None:
        self._raw = raw_by_uid

    async def select(self, _folder: str) -> tuple[str, list[Any]]:
        return "OK", []

    async def uid_search(self, _criteria: str) -> tuple[str, list[Any]]:
        # Ascending UID order (IMAP search default).
        uids = " ".join(sorted(self._raw.keys(), key=int))
        return "OK", [uids.encode()]

    async def uid(self, command: str, *args: str) -> tuple[str, list[Any]]:
        if command != "fetch":
            return "OK", []
        uid_set = args[0]
        uids = uid_set.split(",") if uid_set else []
        out: list[Any] = []
        for uid in uids:
            if uid not in self._raw:
                continue
            # Header line announcing the fetch with FLAGS + UID.
            header_line = (
                f"* {uid} FETCH (UID {uid} FLAGS (\\Seen) "
                f"RFC822.SIZE {len(self._raw[uid])} BODY[HEADER] {{...}}"
            ).encode()
            out.append(header_line)
            # Raw header block (>50 bytes triggers parser ingestion).
            out.append(self._raw[uid])
            out.append(b")")
        return "OK", out

    async def logout(self) -> None:
        return None


async def test_list_emails_thread_view_sorts_by_thread_id_then_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``thread_view=True`` groups emails by thread_id with date asc inside."""

    async def _fake_connect(_mailbox: str) -> _FakeIMAP:
        return _FakeIMAP(_FIXTURE_RAW)

    async def _fake_disconnect(_imap: Any) -> None:
        return None

    monkeypatch.setattr(email_service, "_imap_connect", _fake_connect)
    monkeypatch.setattr(email_service, "_imap_disconnect", _fake_disconnect)

    resp = await email_service.list_emails(
        mailbox="bob@example.com",
        folder="INBOX",
        page=1,
        per_page=50,
        thread_view=True,
    )

    assert resp.total == 3
    # Expected order:
    #   Thread "<a-root@host>" — root then reply (asc within thread)
    #   Thread "<b-only@host>" — standalone
    # Threads themselves sort lexicographically by thread_id:
    #   "<a-root@host>" < "<b-only@host>"
    ordered = [(e.thread_id, e.message_id) for e in resp.emails]
    assert ordered == [
        ("<a-root@host>", "<a-root@host>"),
        ("<a-root@host>", "<a-reply@host>"),
        ("<b-only@host>", "<b-only@host>"),
    ]
