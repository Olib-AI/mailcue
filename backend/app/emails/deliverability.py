"""Deterministic deliverability scoring from the original RFC 5322 message.

The report deliberately uses evidence recorded by the receiving mail stack.
It does not claim to predict provider-specific inbox placement or reputation.
"""

from __future__ import annotations

import re
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Literal, TypeAlias
from urllib.parse import urlparse

from app.config import settings
from app.emails.schemas import (
    DeliverabilityCategory,
    DeliverabilityCheck,
    DeliverabilityEvidence,
    DeliverabilityReport,
)

DELIVERABILITY_SCORE_VERSION = "2.3"

_CATEGORY_TITLES = {
    "authentication": "Authentication",
    "content": "Content quality",
    "headers": "Message setup",
    "transport": "Transport",
    "spam_filter": "Spam filter",
    "attachments": "Attachments",
}
_AUTH_RESULT_RE = re.compile(r"\b(spf|dkim|dmarc)\s*=\s*([a-z]+)", re.IGNORECASE)
_RECEIVED_SPF_RESULT_RE = re.compile(
    r"^\s*(pass|fail|softfail|neutral|none|temperror|permerror)\b", re.IGNORECASE
)
_PROPERTY_RE = re.compile(r"\b([a-z][a-z0-9_.-]*)\s*=\s*(?:\"([^\"]*)\"|([^\s;]+))", re.I)
_SPAM_SCORE_RE = re.compile(r"\bscore=(-?\d+(?:\.\d+)?)", re.I)
_SPAM_REQUIRED_RE = re.compile(r"\brequired=(-?\d+(?:\.\d+)?)", re.I)
_SPAM_TESTS_RE = re.compile(r"\btests=([^\s]+)", re.I)
_SPAM_REPORT_RULE_RE = re.compile(r"^\s*\*?\s*(-?\d+(?:\.\d+)?)\s+([A-Z][A-Z0-9_]+)\s*(.*)$")
_SPAM_RULE_GUIDANCE = {
    "DKIM_INVALID": "Verify the DKIM signature, selector, canonicalization, and signed headers.",
    "DKIM_SIGNED": "The message contains a DKIM signature. This rule is informational.",
    "DMARC_FAIL_REJECT": "Align a passing SPF or DKIM identity with the visible From domain.",
    "HTML_MESSAGE": "This rule only notes that HTML is present and is usually informational.",
    "MISSING_DATE": "Add a valid RFC 5322 Date header.",
    "MISSING_MID": "Add one unique and well-formed Message-ID header.",
    "SPF_FAIL": "Authorize the sending IP in the envelope sender domain SPF record.",
    "SPF_SOFTFAIL": "Replace SPF soft-fail with an accurate authorized sender policy.",
}
_RISKY_PHRASES = (
    "act now",
    "buy now",
    "click here",
    "free money",
    "guaranteed income",
    "limited time",
    "risk free",
    "urgent action",
    "winner",
)


def _css_rgb(value: str) -> tuple[int, int, int] | None:
    value = value.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{3}", value):
        return int(value[1] * 2, 16), int(value[2] * 2, 16), int(value[3] * 2, 16)
    if re.fullmatch(r"#[0-9a-f]{6}", value):
        return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
    match = re.fullmatch(
        r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,[^)]*)?\)",
        value,
    )
    if not match:
        return None
    channels = [min(int(channel), 255) for channel in match.groups()]
    return channels[0], channels[1], channels[2]


def _contrast_ratio(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    def luminance(color: tuple[int, int, int]) -> float:
        channels = [value / 255 for value in color]
        linear = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    low, high = sorted((luminance(left), luminance(right)))
    return (high + 0.05) / (low + 0.05)


def _inline_contrast_failures(styles: list[str]) -> list[str]:
    failures: list[str] = []
    for style in styles:
        declarations = {
            name.strip().lower(): value.strip()
            for declaration in style.split(";")
            if ":" in declaration
            for name, value in [declaration.split(":", 1)]
        }
        foreground = _css_rgb(declarations.get("color", ""))
        background = _css_rgb(
            declarations.get("background-color", declarations.get("background", ""))
        )
        if foreground is None or background is None:
            continue
        ratio = _contrast_ratio(foreground, background)
        if ratio < 4.5:
            failures.append(f"Inline foreground/background contrast: {ratio:.2f}:1")
    return failures[:20]


def _preheader_text(html: str) -> str:
    match = re.search(
        r"<(?:div|span|p)[^>]*style\s*=\s*['\"][^'\"]*"
        r"(?:display\s*:\s*none|max-height\s*:\s*0|opacity\s*:\s*0)"
        r"[^'\"]*['\"][^>]*>(.*?)</(?:div|span|p)>",
        html[:20_000],
        re.I | re.S,
    )
    if match is None:
        return ""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", match.group(1)))).strip()[:500]


DeliverabilityCategoryId: TypeAlias = Literal[
    "authentication",
    "content",
    "headers",
    "transport",
    "spam_filter",
    "attachments",
    "dns",
    "reputation",
    "links",
    "visual",
    "placement",
    "client_previews",
]
DeliverabilityCheckStatus: TypeAlias = Literal["pass", "warning", "fail", "info"]
DeliverabilityVerdict: TypeAlias = Literal["excellent", "good", "needs_work", "poor"]


class _ContentInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.links: list[str] = []
        self.link_labels: list[tuple[str, str]] = []
        self.images = 0
        self.images_without_alt = 0
        self.remote_images = 0
        self.tracking_pixels = 0
        self.scripts = 0
        self.forms = 0
        self.forbidden_tags: Counter[str] = Counter()
        self.hidden_elements = 0
        self.duplicate_attributes = 0
        self.document_language = ""
        self.heading_count = 0
        self.heading_levels: list[int] = []
        self.inline_styles: list[str] = []
        self.small_explicit_tap_targets = 0
        self._hidden_depth = 0
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        lower = tag.lower()
        if len(values) != len(attrs):
            self.duplicate_attributes += len(attrs) - len(values)
        if lower == "html":
            self.document_language = values.get("lang", "").strip()
        if lower in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_count += 1
            self.heading_levels.append(int(lower[1]))
        if values.get("style"):
            self.inline_styles.append(values["style"])
        if lower in {"a", "button"}:
            style_dimensions = {
                name.lower(): int(size)
                for name, size in re.findall(
                    r"(?:^|;)\s*(width|height|min-width|min-height)\s*:\s*(\d+)px",
                    values.get("style", ""),
                    re.I,
                )
            }
            tap_width = int(values["width"]) if values.get("width", "").isdigit() else None
            tap_height = int(values["height"]) if values.get("height", "").isdigit() else None
            tap_width = (
                tap_width or style_dimensions.get("min-width") or style_dimensions.get("width")
            )
            tap_height = (
                tap_height or style_dimensions.get("min-height") or style_dimensions.get("height")
            )
            if (
                tap_width is not None
                and tap_height is not None
                and (tap_width < 44 or tap_height < 44)
            ):
                self.small_explicit_tap_targets += 1
        if lower in {"applet", "audio", "embed", "iframe", "object", "script", "video"}:
            self.forbidden_tags[lower] += 1
        style = values.get("style", "").replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style or "font-size:0" in style:
            self.hidden_elements += 1
        if lower in {"script", "style"}:
            self._hidden_depth += 1
        if lower == "script":
            self.scripts += 1
        elif lower == "form":
            self.forms += 1
        elif lower == "a" and values.get("href"):
            self.links.append(values["href"])
            self._anchor_href = values["href"]
            self._anchor_text = []
        elif lower == "img":
            self.images += 1
            if not values.get("alt", "").strip():
                self.images_without_alt += 1
            source = values.get("src", "")
            if source.lower().startswith(("http://", "https://")):
                self.remote_images += 1
            width = values.get("width", "").strip().rstrip("px")
            height = values.get("height", "").strip().rstrip("px")
            if width.isdigit() and height.isdigit() and int(width) <= 2 and int(height) <= 2:
                self.tracking_pixels += 1

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in {"script", "style"} and self._hidden_depth:
            self._hidden_depth -= 1
        if lower == "a" and self._anchor_href is not None:
            self.link_labels.append((self._anchor_href, " ".join(self._anchor_text).strip()))
            self._anchor_href = None
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.text.append(data)
            if self._anchor_href is not None:
                self._anchor_text.append(data)


def _check(
    check_id: str,
    category: DeliverabilityCategoryId,
    title: str,
    status: DeliverabilityCheckStatus,
    summary: str,
    *,
    points: float,
    max_points: float,
    details: list[str] | None = None,
    evidence: list[DeliverabilityEvidence] | None = None,
    recommendation: str | None = None,
) -> DeliverabilityCheck:
    return DeliverabilityCheck(
        id=check_id,
        category=category,
        title=title,
        status=status,
        summary=summary,
        details=details or [],
        evidence=evidence or [],
        recommendation=recommendation,
        points=points,
        max_points=max_points,
    )


def _domain(address: str) -> str | None:
    parsed = parseaddr(address)[1].lower()
    if "@" not in parsed:
        return None
    domain = parsed.rsplit("@", 1)[1].rstrip(".")
    return domain or None


def _identity_domain(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().strip("<>").lower().rstrip(".")
    if not normalized:
        return None
    if "@" in normalized:
        return _domain(normalized)
    return normalized


def _aligned(left: str | None, right: str | None) -> bool:
    left_domain = _identity_domain(left)
    right_domain = _identity_domain(right)
    if not left_domain or not right_domain:
        return False
    return (
        left_domain == right_domain
        or left_domain.endswith(f".{right_domain}")
        or right_domain.endswith(f".{left_domain}")
    )


def _trusted_authserv_ids() -> set[str]:
    """Return receiver IDs emitted by current and earlier MailCue versions."""
    candidates = {
        "mailcue",
        settings.hostname,
        f"mx1.{settings.domain}",
    }
    return {candidate.strip().lower().rstrip(".") for candidate in candidates if candidate.strip()}


def _authserv_id(value: str) -> str | None:
    preamble, separator, _results = value.partition(";")
    if not separator:
        return None
    tokens = preamble.strip().split()
    if not tokens:
        return None
    return tokens[0].strip('"').lower().rstrip(".") or None


def _parsed_authentication_results(
    msg: EmailMessage,
) -> dict[str, list[tuple[str, dict[str, str]]]]:
    trusted_ids = _trusted_authserv_ids()
    parsed: dict[str, list[tuple[str, dict[str, str]]]] = {}

    for raw_result in msg.get_all("Authentication-Results", []):
        value = str(raw_result)
        if _authserv_id(value) not in trusted_ids:
            continue
        for segment in value.split(";")[1:]:
            result_match = _AUTH_RESULT_RE.search(segment)
            if not result_match:
                continue
            method, result = result_match.groups()
            properties = {
                match.group(1).lower(): match.group(2) or match.group(3)
                for match in _PROPERTY_RE.finditer(segment)
            }
            parsed.setdefault(method.lower(), []).append((result.lower(), properties))

    # MailCue releases before score model 2.3 used policyd-spf's default
    # Received-SPF output. Accept it only when its receiver identifies this
    # deployment, so an imported or sender-forged field cannot earn points.
    if "spf" not in parsed:
        for raw_result in msg.get_all("Received-SPF", []):
            value = str(raw_result)
            result_match = _RECEIVED_SPF_RESULT_RE.match(value)
            if not result_match:
                continue
            properties = {
                match.group(1).lower(): match.group(2) or match.group(3)
                for match in _PROPERTY_RE.finditer(value)
            }
            receiver = _identity_domain(properties.get("receiver"))
            if receiver not in trusted_ids:
                continue
            parsed.setdefault("spf", []).append(
                (
                    result_match.group(1).lower(),
                    {
                        "smtp.mailfrom": properties.get("envelope-from", ""),
                        "smtp.helo": properties.get("helo", ""),
                    },
                )
            )
            break

    return parsed


def trusted_spf_domain(msg: EmailMessage) -> str | None:
    """Return the receiver-verified MAIL FROM domain, with HELO as its fallback."""
    results = _parsed_authentication_results(msg).get("spf", [])
    passing = next((item for item in results if item[0] == "pass"), None)
    best = passing or (results[0] if results else None)
    if best is None:
        return None
    properties = best[1]
    return _identity_domain(properties.get("smtp.mailfrom")) or _identity_domain(
        properties.get("smtp.helo")
    )


def _authentication_checks(
    msg: EmailMessage, sender_domain: str | None
) -> list[DeliverabilityCheck]:
    parsed = _parsed_authentication_results(msg)

    definitions = (
        ("spf", 10.0, "SPF", "Publish SPF for the envelope sender and authorize this sending IP."),
        ("dkim", 15.0, "DKIM", "Sign the message with DKIM using the visible From domain."),
        (
            "dmarc",
            15.0,
            "DMARC",
            "Publish DMARC and align SPF or DKIM with the visible From domain.",
        ),
    )
    checks: list[DeliverabilityCheck] = []
    for method, weight, title, recommendation in definitions:
        results = parsed.get(method, [])
        passing = next((item for item in results if item[0] == "pass"), None)
        best = passing or (results[0] if results else None)
        if best is None:
            checks.append(
                _check(
                    method,
                    "authentication",
                    title,
                    "fail",
                    f"No receiver-verified {title} result was found.",
                    points=0,
                    max_points=weight,
                    recommendation=recommendation,
                )
            )
            continue
        result, properties = best
        auth_domain = _identity_domain(properties.get("header.from"))
        if method == "spf":
            auth_domain = _identity_domain(properties.get("smtp.mailfrom")) or _identity_domain(
                properties.get("smtp.helo")
            )
        elif method == "dkim":
            auth_domain = _identity_domain(properties.get("header.d"))
        alignment = _aligned(auth_domain, sender_domain)
        details = [f"Receiver result: {result}"]
        if auth_domain:
            details.append(f"Authenticated domain: {auth_domain}")
        if method in {"spf", "dkim"} and result == "pass":
            details.append(f"Visible From alignment: {'aligned' if alignment else 'not aligned'}")
        status: DeliverabilityCheckStatus
        if result == "pass" and (method == "dmarc" or alignment):
            status, points = "pass", weight
            summary = f"{title} passed" + (" with aligned identity." if method != "dmarc" else ".")
        elif result == "pass":
            status, points = "warning", weight * 0.6
            summary = (
                f"{title} passed, but its domain is not aligned with the visible From domain."
            )
        elif result in {"neutral", "none", "softfail", "temperror"}:
            status, points = "warning", weight * 0.25
            summary = f"The receiver reported {title} {result}."
        else:
            status, points = "fail", 0
            summary = f"The receiver reported {title} {result}."
        checks.append(
            _check(
                method,
                "authentication",
                title,
                status,
                summary,
                points=points,
                max_points=weight,
                details=details,
                recommendation=None if status == "pass" else recommendation,
            )
        )
    return checks


def _message_bodies(msg: EmailMessage) -> tuple[str, str, _ContentInspector]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            value = part.get_content()
        except (LookupError, UnicodeError):
            payload = part.get_payload(decode=True) or b""
            value = (
                payload.decode("utf-8", errors="replace")
                if isinstance(payload, bytes)
                else str(payload)
            )
        if content_type == "text/plain":
            plain_parts.append(str(value))
        else:
            html_parts.append(str(value))
    plain = "\n".join(plain_parts).strip()
    html = "\n".join(html_parts).strip()
    inspector = _ContentInspector()
    if html:
        with suppress(Exception):
            inspector.feed(html)
    return plain, html, inspector


def _content_checks(msg: EmailMessage) -> list[DeliverabilityCheck]:
    plain, html, inspector = _message_bodies(msg)
    preheader = _preheader_text(html) if html else ""
    visible_html = re.sub(r"\s+", " ", " ".join(inspector.text)).strip()
    combined = f"{msg.get('Subject', '')} {plain or visible_html}".lower()
    checks: list[DeliverabilityCheck] = []
    if plain and html:
        checks.append(
            _check(
                "body_alternatives",
                "content",
                "Body alternatives",
                "pass",
                "Both plain-text and HTML versions are present.",
                points=4,
                max_points=4,
            )
        )
    elif plain:
        checks.append(
            _check(
                "body_alternatives",
                "content",
                "Body alternatives",
                "pass",
                "A readable plain-text body is present.",
                points=4,
                max_points=4,
            )
        )
    elif html:
        checks.append(
            _check(
                "body_alternatives",
                "content",
                "Body alternatives",
                "warning",
                "The message has HTML but no plain-text alternative.",
                points=2,
                max_points=4,
                recommendation="Add a meaningful text/plain alternative for accessibility and filtering resilience.",
            )
        )
    else:
        checks.append(
            _check(
                "body_alternatives",
                "content",
                "Body alternatives",
                "fail",
                "No readable text or HTML body was found.",
                points=0,
                max_points=4,
                recommendation="Include a non-empty message body.",
            )
        )

    if html:
        text_length = len(visible_html)
        markup_ratio = len(html) / max(text_length, 1)
        unsafe = sum(inspector.forbidden_tags.values()) + inspector.forms
        if unsafe:
            checks.append(
                _check(
                    "html_quality",
                    "content",
                    "HTML quality",
                    "fail",
                    "The HTML contains unsupported active content.",
                    points=0,
                    max_points=4,
                    details=[
                        "Unsupported tags: "
                        + ", ".join(
                            f"{tag} ({count})"
                            for tag, count in sorted(inspector.forbidden_tags.items())
                        ),
                        f"Form tags: {inspector.forms}",
                    ],
                    recommendation="Remove scripts and forms from email HTML.",
                )
            )
        elif text_length < 40 and len(html) > 500:
            checks.append(
                _check(
                    "html_quality",
                    "content",
                    "HTML quality",
                    "warning",
                    "The HTML contains very little visible text.",
                    points=2,
                    max_points=4,
                    recommendation="Add useful copy and avoid an image-only message.",
                )
            )
        elif markup_ratio > 30:
            checks.append(
                _check(
                    "html_quality",
                    "content",
                    "HTML quality",
                    "warning",
                    "The HTML-to-visible-text ratio is unusually high.",
                    points=2.5,
                    max_points=4,
                    recommendation="Simplify the markup and include more meaningful visible text.",
                )
            )
        else:
            checks.append(
                _check(
                    "html_quality",
                    "content",
                    "HTML quality",
                    "pass",
                    "The HTML has a reasonable amount of visible content.",
                    points=4,
                    max_points=4,
                )
            )
    else:
        checks.append(
            _check(
                "html_quality",
                "content",
                "HTML quality",
                "info",
                "No HTML body was supplied, so HTML checks do not apply.",
                points=0,
                max_points=0,
            )
        )

    subject = str(msg.get("Subject", "")).strip()
    if not subject:
        checks.append(
            _check(
                "subject_quality",
                "content",
                "Subject line",
                "fail",
                "The subject line is missing.",
                points=0,
                max_points=4,
                recommendation="Add a concise subject that accurately describes the message.",
            )
        )
    elif len(subject) > 120 or subject.count("!") >= 4 or (subject.isupper() and len(subject) > 8):
        checks.append(
            _check(
                "subject_quality",
                "content",
                "Subject line",
                "warning",
                "The subject uses patterns commonly associated with low-quality mail.",
                points=2,
                max_points=4,
                details=[f"Length: {len(subject)} characters"],
                recommendation="Use a concise, natural subject with restrained punctuation and capitalization.",
            )
        )
    else:
        checks.append(
            _check(
                "subject_quality",
                "content",
                "Subject line",
                "pass",
                "The subject is present and reasonably formatted.",
                points=4,
                max_points=4,
            )
        )

    phrase_counts = Counter(phrase for phrase in _RISKY_PHRASES if phrase in combined)
    if len(phrase_counts) >= 3:
        checks.append(
            _check(
                "risky_language",
                "content",
                "Promotional language",
                "warning",
                "Several high-pressure phrases were detected.",
                points=1,
                max_points=4,
                details=sorted(phrase_counts),
                recommendation="Rewrite high-pressure or misleading language in a direct, specific tone.",
            )
        )
    elif phrase_counts:
        checks.append(
            _check(
                "risky_language",
                "content",
                "Promotional language",
                "warning",
                "A potentially high-pressure phrase was detected.",
                points=3,
                max_points=4,
                details=sorted(phrase_counts),
                recommendation="Review the flagged phrase in context.",
            )
        )
    else:
        checks.append(
            _check(
                "risky_language",
                "content",
                "Promotional language",
                "pass",
                "No obvious high-pressure phrase patterns were detected.",
                points=4,
                max_points=4,
            )
        )

    unsafe_links = []
    for link in inspector.links:
        parsed = urlparse(link)
        if parsed.scheme.lower() not in {"http", "https", "mailto", "tel", ""} or (
            parsed.hostname and re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", parsed.hostname)
        ):
            unsafe_links.append(link)
    if unsafe_links:
        checks.append(
            _check(
                "link_hygiene",
                "content",
                "Link hygiene",
                "fail",
                "The message contains suspicious link targets.",
                points=0,
                max_points=2,
                details=unsafe_links[:10],
                recommendation="Use HTTPS links on recognizable domains and remove executable or raw-IP targets.",
            )
        )
    else:
        checks.append(
            _check(
                "link_hygiene",
                "content",
                "Link hygiene",
                "pass",
                f"No suspicious targets were found across {len(inspector.links)} link(s).",
                points=2,
                max_points=2,
            )
        )

    mismatched_links: list[str] = []
    insecure_links = 0
    for href, label in inspector.link_labels:
        target = urlparse(href)
        if target.scheme.lower() == "http":
            insecure_links += 1
        label_match = re.search(r"https?://[^\s<>]+", label, re.I)
        if not label_match or not target.hostname:
            continue
        label_host = urlparse(label_match.group(0).rstrip(".,;)")).hostname
        if label_host and label_host.lower() != target.hostname.lower():
            mismatched_links.append(f"Displayed {label_host}, targets {target.hostname}")
    if mismatched_links:
        checks.append(
            _check(
                "link_identity",
                "content",
                "Link identity",
                "fail",
                "Some visible URL labels point to a different host.",
                points=0,
                max_points=2,
                details=mismatched_links[:10],
                recommendation="Make displayed URL hosts match their actual destinations.",
            )
        )
    elif insecure_links:
        checks.append(
            _check(
                "link_identity",
                "content",
                "Link identity",
                "warning",
                "Some web links use unencrypted HTTP.",
                points=1,
                max_points=2,
                details=[f"HTTP links: {insecure_links}"],
                recommendation="Use HTTPS for web destinations.",
            )
        )
    else:
        checks.append(
            _check(
                "link_identity",
                "content",
                "Link identity",
                "pass",
                "Visible link labels and target schemes do not show obvious deception.",
                points=2,
                max_points=2,
            )
        )

    suspicious_hidden = max(0, inspector.hidden_elements - (1 if preheader else 0))
    if suspicious_hidden:
        checks.append(
            _check(
                "hidden_content",
                "content",
                "Hidden content",
                "warning",
                "The HTML contains visually hidden elements that filters may scrutinize.",
                points=1,
                max_points=2,
                details=[f"Hidden elements outside the detected preheader: {suspicious_hidden}"],
                recommendation="Remove hidden copy unless it has a clear accessibility or layout purpose.",
            )
        )
    else:
        checks.append(
            _check(
                "hidden_content",
                "content",
                "Hidden content",
                "pass",
                "No common hidden-text techniques were detected.",
                points=2,
                max_points=2,
            )
        )

    if inspector.tracking_pixels:
        checks.append(
            _check(
                "tracking_pixels",
                "content",
                "Tracking pixels",
                "warning",
                "Tiny remote images consistent with tracking pixels were detected.",
                points=0,
                max_points=1,
                details=[f"Likely tracking pixels: {inspector.tracking_pixels}"],
                recommendation="Use tracking only when consent, privacy policy, and message purpose allow it.",
            )
        )
    else:
        checks.append(
            _check(
                "tracking_pixels",
                "content",
                "Tracking pixels",
                "pass",
                "No tiny remote tracking images were detected.",
                points=1,
                max_points=1,
            )
        )

    if html and not inspector.document_language:
        checks.append(
            _check(
                "document_accessibility",
                "content",
                "Document accessibility",
                "warning",
                "The HTML document does not declare a language.",
                points=1,
                max_points=2,
                recommendation="Set the html lang attribute to the message language.",
            )
        )
    else:
        checks.append(
            _check(
                "document_accessibility",
                "content",
                "Document accessibility",
                "pass",
                "The HTML language is declared or the message is plain text.",
                points=2,
                max_points=2,
            )
        )

    if html:
        checks.append(
            _check(
                "preheader",
                "content",
                "Preview preheader",
                "pass" if 40 <= len(preheader) <= 130 else "warning" if preheader else "info",
                "A concise hidden preheader was detected."
                if 40 <= len(preheader) <= 130
                else "The hidden preheader may be too short or too long."
                if preheader
                else "No common hidden preheader pattern was detected. This is optional.",
                points=1 if 40 <= len(preheader) <= 130 else 0,
                max_points=1 if preheader else 0,
                details=[f"Detected preheader length: {len(preheader)} characters"]
                if preheader
                else [],
                recommendation="Use a useful preheader of roughly 40 to 130 characters."
                if preheader and not 40 <= len(preheader) <= 130
                else None,
            )
        )
        heading_skips = sum(
            current > previous + 1
            for previous, current in zip(
                inspector.heading_levels, inspector.heading_levels[1:], strict=False
            )
        )
        checks.append(
            _check(
                "heading_order",
                "content",
                "Heading order",
                "warning" if heading_skips else "pass",
                f"The heading structure skips {heading_skips} level(s)."
                if heading_skips
                else "No skipped HTML heading levels were detected.",
                points=0 if heading_skips else 1,
                max_points=1,
                details=[
                    f"Heading sequence: {', '.join(f'h{level}' for level in inspector.heading_levels)}"
                ]
                if inspector.heading_levels
                else [],
                recommendation="Use headings in a logical sequence without skipping levels."
                if heading_skips
                else None,
            )
        )
        contrast_failures = _inline_contrast_failures(inspector.inline_styles)
        checks.append(
            _check(
                "inline_color_contrast",
                "content",
                "Inline color contrast",
                "warning" if contrast_failures else "pass",
                "Some explicit inline foreground and background colors are below 4.5:1."
                if contrast_failures
                else "No low-contrast explicit inline color pairs were detected.",
                points=0 if contrast_failures else 2,
                max_points=2,
                details=contrast_failures,
                recommendation="Use WCAG AA color contrast and verify inherited, image, and dark-mode colors in previews."
                if contrast_failures
                else None,
            )
        )
        checks.append(
            _check(
                "tap_target_size",
                "content",
                "Tap target size",
                "warning" if inspector.small_explicit_tap_targets else "pass",
                f"{inspector.small_explicit_tap_targets} explicitly sized link or button target(s) are below 44 by 44 pixels."
                if inspector.small_explicit_tap_targets
                else "No undersized explicitly dimensioned link or button targets were detected.",
                points=0 if inspector.small_explicit_tap_targets else 1,
                max_points=1,
                recommendation="Make important touch targets at least 44 by 44 CSS pixels."
                if inspector.small_explicit_tap_targets
                else None,
            )
        )
        css_risks = {
            "CSS animations": len(re.findall(r"@keyframes|\banimation\s*:", html, re.I)),
            "CSS variables": len(re.findall(r"var\s*\(--|--[a-z0-9_-]+\s*:", html, re.I)),
            "Fixed positioning": len(re.findall(r"position\s*:\s*fixed", html, re.I)),
            "Grid layout": len(re.findall(r"display\s*:\s*grid", html, re.I)),
            "External font imports": len(
                re.findall(r"@import\s+url|@font-face[^}]*https?://", html, re.I | re.S)
            ),
        }
        found_css_risks = [f"{name}: {count}" for name, count in css_risks.items() if count]
        checks.append(
            _check(
                "email_client_css",
                "content",
                "Email client CSS compatibility",
                "warning" if found_css_risks else "pass",
                "The HTML uses CSS features with uneven email-client support."
                if found_css_risks
                else "No commonly unsupported CSS feature was detected.",
                points=1 if found_css_risks else 2,
                max_points=2,
                details=found_css_risks,
                recommendation="Use progressively enhanced, inlined email CSS and test critical clients."
                if found_css_risks
                else None,
            )
        )

    if inspector.images and inspector.images_without_alt:
        checks.append(
            _check(
                "image_accessibility",
                "content",
                "Image accessibility",
                "warning",
                "Some images are missing alternative text.",
                points=1,
                max_points=2,
                details=[
                    f"Images without alt text: {inspector.images_without_alt} of {inspector.images}"
                ],
                recommendation="Add concise alt text to meaningful images and empty alt text to decorative images.",
            )
        )
    else:
        checks.append(
            _check(
                "image_accessibility",
                "content",
                "Image accessibility",
                "pass",
                "Images include alternative text or no images are present.",
                points=2,
                max_points=2,
            )
        )
    return checks


def _attachment_checks(msg: EmailMessage) -> list[DeliverabilityCheck]:
    attachments = [part for part in msg.walk() if part.get_content_disposition() == "attachment"]
    if not attachments:
        return [
            _check(
                "attachment_safety",
                "attachments",
                "Attachment safety",
                "info",
                "The message has no attachments.",
                points=0,
                max_points=0,
            )
        ]
    dangerous_extensions = {
        ".app",
        ".bat",
        ".cmd",
        ".com",
        ".exe",
        ".hta",
        ".jar",
        ".js",
        ".lnk",
        ".msi",
        ".ps1",
        ".scr",
        ".vbs",
    }
    dangerous: list[str] = []
    oversized: list[str] = []
    total_bytes = 0
    for part in attachments[:100]:
        filename = part.get_filename() or "unnamed attachment"
        payload = part.get_payload(decode=True)
        size = len(payload) if isinstance(payload, bytes) else 0
        total_bytes += size
        suffixes = [suffix.lower() for suffix in re.findall(r"\.[a-z0-9]{1,8}", filename)]
        if any(suffix in dangerous_extensions for suffix in suffixes):
            dangerous.append(filename)
        if size > 10 * 1024 * 1024:
            oversized.append(f"{filename}: {size / 1024 / 1024:.1f} MB")
    details = [
        f"Attachments: {len(attachments)}",
        f"Decoded attachment size: {total_bytes / 1024 / 1024:.1f} MB",
    ]
    if dangerous:
        return [
            _check(
                "attachment_safety",
                "attachments",
                "Attachment safety",
                "fail",
                "Executable or commonly blocked attachment types were detected.",
                points=0,
                max_points=5,
                details=details + dangerous[:20],
                recommendation="Remove executable attachments and share files through a trusted HTTPS service.",
            )
        ]
    if oversized or total_bytes > 20 * 1024 * 1024:
        return [
            _check(
                "attachment_safety",
                "attachments",
                "Attachment safety",
                "warning",
                "Attachment size may exceed receiving-provider limits.",
                points=2,
                max_points=5,
                details=details + oversized[:20],
                recommendation="Keep the encoded message below common provider limits or send a download link.",
            )
        ]
    return [
        _check(
            "attachment_safety",
            "attachments",
            "Attachment safety",
            "pass",
            "Attachment names, types, and decoded size do not show common delivery risks.",
            points=5,
            max_points=5,
            details=details,
        )
    ]


def _header_checks(msg: EmailMessage, sender_domain: str | None) -> list[DeliverabilityCheck]:
    checks: list[DeliverabilityCheck] = []
    from_values = msg.get_all("From", [])
    valid_from = len(from_values) == 1 and bool(parseaddr(str(from_values[0]))[1])
    checks.append(
        _check(
            "from_header",
            "headers",
            "From identity",
            "pass" if valid_from else "fail",
            "One valid From identity is present."
            if valid_from
            else "The message must contain exactly one valid From header.",
            points=3 if valid_from else 0,
            max_points=3,
            recommendation=None
            if valid_from
            else "Send with exactly one syntactically valid From mailbox.",
        )
    )

    duplicate_names = [
        name
        for name in ("Date", "From", "Message-ID", "Reply-To", "Subject")
        if len(msg.get_all(name, [])) > 1
    ]
    checks.append(
        _check(
            "duplicate_headers",
            "headers",
            "Duplicate identity headers",
            "fail" if duplicate_names else "pass",
            "Conflicting singleton headers were found."
            if duplicate_names
            else "No conflicting singleton identity headers were found.",
            points=0 if duplicate_names else 2,
            max_points=2,
            details=duplicate_names,
            recommendation="Emit only one Date, From, Message-ID, Reply-To, and Subject header."
            if duplicate_names
            else None,
        )
    )

    message_ids = msg.get_all("Message-ID", [])
    valid_message_id = len(message_ids) == 1 and bool(
        re.fullmatch(r"\s*<[^<>\s]+@[^<>\s]+>\s*", str(message_ids[0]))
    )
    checks.append(
        _check(
            "message_id",
            "headers",
            "Message ID",
            "pass" if valid_message_id else "warning",
            "A well-formed Message-ID is present."
            if valid_message_id
            else "A unique, well-formed Message-ID was not found.",
            points=3 if valid_message_id else 1,
            max_points=3,
            recommendation=None
            if valid_message_id
            else "Generate one stable Message-ID in angle brackets for each message.",
        )
    )

    date_valid = False
    with suppress(TypeError, ValueError, OverflowError):
        date_valid = parsedate_to_datetime(str(msg.get("Date", ""))) is not None
    checks.append(
        _check(
            "date_header",
            "headers",
            "Date header",
            "pass" if date_valid else "warning",
            "The Date header is valid."
            if date_valid
            else "The Date header is missing or invalid.",
            points=2 if date_valid else 1,
            max_points=2,
            recommendation=None
            if date_valid
            else "Add an RFC 5322 Date header when the message is created.",
        )
    )

    mime_version = str(msg.get("MIME-Version", ""))
    mime_ok = not msg.is_multipart() or mime_version == "1.0"
    checks.append(
        _check(
            "mime_structure",
            "headers",
            "MIME structure",
            "pass" if mime_ok else "warning",
            "The MIME declaration matches the message structure."
            if mime_ok
            else "A multipart message is missing MIME-Version: 1.0.",
            points=2 if mime_ok else 1,
            max_points=2,
            recommendation=None
            if mime_ok
            else "Add MIME-Version: 1.0 and validate MIME boundaries.",
        )
    )

    bulk = any(msg.get(name) for name in ("List-ID", "Precedence", "List-Unsubscribe"))
    unsubscribe = bool(msg.get("List-Unsubscribe"))
    one_click = "list-unsubscribe=one-click" in str(msg.get("List-Unsubscribe-Post", "")).lower()
    if not bulk:
        checks.append(
            _check(
                "unsubscribe",
                "headers",
                "Unsubscribe support",
                "info",
                "The message does not identify itself as bulk mail, so unsubscribe headers are not required.",
                points=0,
                max_points=0,
            )
        )
    elif unsubscribe and one_click:
        checks.append(
            _check(
                "unsubscribe",
                "headers",
                "Unsubscribe support",
                "pass",
                "Bulk mail includes unsubscribe and one-click support.",
                points=3,
                max_points=3,
            )
        )
    elif unsubscribe:
        checks.append(
            _check(
                "unsubscribe",
                "headers",
                "Unsubscribe support",
                "warning",
                "An unsubscribe method is present, but RFC 8058 one-click support is missing.",
                points=2,
                max_points=3,
                recommendation="Add List-Unsubscribe-Post: List-Unsubscribe=One-Click for eligible bulk mail.",
            )
        )
    else:
        checks.append(
            _check(
                "unsubscribe",
                "headers",
                "Unsubscribe support",
                "fail",
                "Bulk mail does not include a List-Unsubscribe header.",
                points=0,
                max_points=3,
                recommendation="Add working mailto or HTTPS List-Unsubscribe options.",
            )
        )

    return_path_domain = _domain(str(msg.get("Return-Path", "")))
    aligned = _aligned(return_path_domain, sender_domain)
    if return_path_domain and aligned:
        checks.append(
            _check(
                "envelope_alignment",
                "headers",
                "Envelope alignment",
                "pass",
                "The Return-Path domain aligns with the visible From domain.",
                points=2,
                max_points=2,
            )
        )
    elif return_path_domain:
        checks.append(
            _check(
                "envelope_alignment",
                "headers",
                "Envelope alignment",
                "warning",
                "The Return-Path domain does not align with the visible From domain.",
                points=1,
                max_points=2,
                details=[f"Return-Path domain: {return_path_domain}"],
                recommendation="Use an aligned custom bounce domain when possible.",
            )
        )
    else:
        checks.append(
            _check(
                "envelope_alignment",
                "headers",
                "Envelope alignment",
                "warning",
                "No usable Return-Path domain was found.",
                points=1,
                max_points=2,
                recommendation="Configure a valid envelope sender for bounce handling and SPF alignment.",
            )
        )
    reply_to = str(msg.get("Reply-To", ""))
    reply_domain = _domain(reply_to)
    if not reply_to:
        checks.append(
            _check(
                "reply_to_identity",
                "headers",
                "Reply-To identity",
                "info",
                "No Reply-To override is present.",
                points=0,
                max_points=0,
            )
        )
    elif reply_domain and _aligned(reply_domain, sender_domain):
        checks.append(
            _check(
                "reply_to_identity",
                "headers",
                "Reply-To identity",
                "pass",
                "The Reply-To domain aligns with the visible From domain.",
                points=2,
                max_points=2,
            )
        )
    else:
        checks.append(
            _check(
                "reply_to_identity",
                "headers",
                "Reply-To identity",
                "warning",
                "The Reply-To address is invalid or uses an unrelated domain.",
                points=1,
                max_points=2,
                details=[f"Reply-To: {reply_to[:320]}"],
                recommendation="Use an expected, monitored Reply-To domain and explain intentional differences.",
            )
        )
    return checks


def _transport_checks(msg: EmailMessage) -> list[DeliverabilityCheck]:
    received = [str(value) for value in msg.get_all("Received", [])]
    tls_hops = [value for value in received if re.search(r"\b(?:TLS|ESMTPS)\b", value, re.I)]
    if received and tls_hops:
        tls = _check(
            "transport_tls",
            "transport",
            "Transport encryption",
            "pass",
            "At least one recorded delivery hop used TLS.",
            points=4,
            max_points=4,
            details=[f"TLS hops: {len(tls_hops)} of {len(received)}"],
        )
    elif received:
        tls = _check(
            "transport_tls",
            "transport",
            "Transport encryption",
            "warning",
            "No TLS evidence was found in the recorded delivery route.",
            points=1,
            max_points=4,
            recommendation="Require opportunistic or enforced TLS between sending and receiving MTAs.",
        )
    else:
        tls = _check(
            "transport_tls",
            "transport",
            "Transport encryption",
            "info",
            "No Received route was available, so transport encryption cannot be assessed.",
            points=0,
            max_points=0,
        )

    route = _check(
        "received_route",
        "transport",
        "Delivery route",
        "pass" if received else "info",
        f"The message contains {len(received)} delivery hop(s)."
        if received
        else "No delivery route is available for this message.",
        points=2 if received else 0,
        max_points=2 if received else 0,
    )
    named_origin = bool(received and re.search(r"\bfrom\s+[a-z0-9.-]+", received[-1], re.I))
    origin = _check(
        "origin_identity",
        "transport",
        "Origin identity",
        "pass" if named_origin else "warning" if received else "info",
        "The earliest recorded hop includes a named sending host."
        if named_origin
        else "The sending host identity could not be established from the route.",
        points=2 if named_origin else 1 if received else 0,
        max_points=2 if received else 0,
        recommendation=None
        if named_origin or not received
        else "Configure a stable sending hostname and matching reverse DNS.",
    )
    arc = bool(msg.get("ARC-Seal") and msg.get("ARC-Message-Signature"))
    arc_check = _check(
        "arc",
        "transport",
        "ARC chain",
        "pass" if arc else "info",
        "An ARC chain is present for forwarded authentication evidence."
        if arc
        else "No ARC chain is present. ARC is optional unless the message was forwarded.",
        points=2 if arc else 0,
        max_points=2 if arc else 0,
    )
    return [tls, route, origin, arc_check]


def _spam_rule_evidence(msg: EmailMessage, status_value: str) -> list[DeliverabilityEvidence]:
    """Parse rule names and optional scores without treating sender headers as trusted input."""
    evidence_by_code: dict[str, DeliverabilityEvidence] = {}
    tests_match = _SPAM_TESTS_RE.search(status_value)
    if tests_match:
        for raw_code in tests_match.group(1).split(","):
            code = raw_code.strip().upper()
            if not code or not re.fullmatch(r"[A-Z0-9_]{1,80}", code):
                continue
            evidence_by_code[code] = DeliverabilityEvidence(
                code=code,
                title=code.replace("_", " ").title(),
                description="Matched by the local SpamAssassin ruleset.",
                recommendation=_SPAM_RULE_GUIDANCE.get(code),
            )

    report = str(msg.get("X-Spam-Report", ""))
    for line in report.splitlines()[:200]:
        match = _SPAM_REPORT_RULE_RE.match(line)
        if not match:
            continue
        raw_score, code, description = match.groups()
        current = evidence_by_code.get(code)
        evidence_by_code[code] = DeliverabilityEvidence(
            code=code,
            title=current.title if current else code.replace("_", " ").title(),
            score=float(raw_score),
            description=description.strip()[:500]
            or (current.description if current else "Matched by the local SpamAssassin ruleset."),
            recommendation=_SPAM_RULE_GUIDANCE.get(code),
        )
    return sorted(
        evidence_by_code.values(),
        key=lambda item: (-(item.score or 0), item.code),
    )[:100]


def _spam_filter_checks(msg: EmailMessage) -> list[DeliverabilityCheck]:
    status_value = str(msg.get("X-Spam-Status", ""))
    flag_value = str(msg.get("X-Spam-Flag", ""))
    if not status_value and not flag_value:
        return [
            _check(
                "spamassassin",
                "spam_filter",
                "SpamAssassin",
                "info",
                "No local SpamAssassin result was attached to this message.",
                points=0,
                max_points=0,
            )
        ]
    score_match = _SPAM_SCORE_RE.search(status_value)
    required_match = _SPAM_REQUIRED_RE.search(status_value)
    score = float(score_match.group(1)) if score_match else None
    required = float(required_match.group(1)) if required_match else 5.0
    flagged = flag_value.strip().lower() == "yes" or status_value.lower().startswith("yes")
    evidence = _spam_rule_evidence(msg, status_value)
    details = []
    if score is not None:
        details.append(f"SpamAssassin score: {score:g}, threshold: {required:g}")
    status: DeliverabilityCheckStatus
    if flagged:
        points, status = 0.0, "fail"
        summary = "The local spam filter classified the message as spam."
    elif score is None:
        points, status = 9.0, "warning"
        summary = (
            "The local spam filter did not flag the message, but no numeric score was recorded."
        )
    else:
        margin = required - score
        points = 12.0 if margin >= 2 else 9.0 if margin >= 0.5 else 6.0
        status = "pass" if points == 12 else "warning"
        summary = (
            "The local spam filter accepted the message."
            if status == "pass"
            else "The message passed the local spam filter with limited margin."
        )
    main = _check(
        "spamassassin",
        "spam_filter",
        "SpamAssassin",
        status,
        summary,
        points=points,
        max_points=12,
        details=details,
        evidence=evidence,
        recommendation=None
        if status == "pass"
        else "Review the SpamAssassin rules in X-Spam-Report and fix the highest-impact findings.",
    )
    flag = _check(
        "spam_flag",
        "spam_filter",
        "Spam flag",
        "fail" if flagged else "pass",
        "X-Spam-Flag is YES." if flagged else "X-Spam-Flag does not classify the message as spam.",
        points=0 if flagged else 3,
        max_points=3,
    )
    return [main, flag]


def score_deliverability(
    raw: bytes, *, mailbox: str, uid: str, folder: str
) -> DeliverabilityReport:
    """Build a bounded report without making network requests or executing message content."""
    msg = message_from_bytes(raw, policy=policy.default)
    if not isinstance(msg, EmailMessage):
        raise ValueError("Unable to parse message")
    sender_domain = _domain(str(msg.get("From", "")))
    grouped: dict[DeliverabilityCategoryId, list[DeliverabilityCheck]] = {
        "authentication": _authentication_checks(msg, sender_domain),
        "content": _content_checks(msg),
        "headers": _header_checks(msg, sender_domain),
        "transport": _transport_checks(msg),
        "spam_filter": _spam_filter_checks(msg),
        "attachments": _attachment_checks(msg),
    }
    categories: list[DeliverabilityCategory] = []
    all_checks: list[DeliverabilityCheck] = []
    total_points = 0.0
    total_max = 0.0
    for category_id, checks in grouped.items():
        points = sum(check.points for check in checks)
        max_points = sum(check.max_points for check in checks)
        total_points += points
        total_max += max_points
        all_checks.extend(checks)
        categories.append(
            DeliverabilityCategory(
                id=category_id,
                title=_CATEGORY_TITLES[category_id],
                score=round(points / max_points * 100) if max_points else None,
                points=round(points, 1),
                max_points=round(max_points, 1),
                checks=checks,
            )
        )
    score = max(0, min(100, round(total_points / total_max * 100))) if total_max else 0
    if score >= 90:
        verdict: DeliverabilityVerdict
        verdict, summary = (
            "excellent",
            "Strong technical setup with no major deliverability issues detected.",
        )
    elif score >= 75:
        verdict, summary = "good", "Good foundation with a few improvements worth making."
    elif score >= 50:
        verdict, summary = (
            "needs_work",
            "Several issues may reduce inbox placement and sender trust.",
        )
    else:
        verdict, summary = (
            "poor",
            "Critical issues are likely to harm delivery or filtering outcomes.",
        )
    ranked = sorted(
        (check for check in all_checks if check.recommendation and check.max_points),
        key=lambda check: (check.points / check.max_points, -check.max_points, check.id),
    )
    recommendations = list(
        dict.fromkeys(check.recommendation for check in ranked if check.recommendation)
    )[:5]
    return DeliverabilityReport(
        score_version=DELIVERABILITY_SCORE_VERSION,
        score=score,
        verdict=verdict,
        summary=summary,
        mailbox=mailbox,
        uid=uid,
        folder=folder,
        message_id=str(msg.get("Message-ID", "")),
        sender_domain=sender_domain,
        generated_at=datetime.now(UTC),
        categories=categories,
        top_recommendations=recommendations,
        limitations=[
            "This report does not measure sender reputation or provider-specific inbox placement.",
            "Blocklist checks are not run because public DNS lists have provider and privacy constraints.",
            "A high score improves readiness but cannot guarantee inbox placement.",
        ],
    )
