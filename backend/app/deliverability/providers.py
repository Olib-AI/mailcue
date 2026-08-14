"""Secure adapters for optional external deliverability services."""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import settings
from app.deliverability.links import _public_addresses
from app.deliverability.models import DeliverabilityProvider
from app.deliverability.secrets import decrypt_provider_secret

_MAX_PROVIDER_RESPONSE_BYTES = 20 * 1024 * 1024
_MAX_PREVIEWS = 100


@dataclass(frozen=True)
class PreviewResult:
    client: str
    platform: str
    theme: str
    status: str
    description: str
    media_type: str | None = None
    data: bytes | None = None


@dataclass(frozen=True)
class AnalysisFinding:
    severity: str
    title: str
    detail: str
    recommendation: str


@dataclass(frozen=True)
class AnalysisResult:
    summary: str
    findings: list[AnalysisFinding]


def _decode_image(value: object, media_type: object) -> tuple[str | None, bytes | None]:
    if not isinstance(value, str) or not value:
        return None, None
    if media_type not in {"image/png", "image/jpeg"}:
        return None, None
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None, None
    if len(data) > settings.deliverability_artifact_max_bytes:
        return None, None
    valid = (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        if media_type == "image/png"
        else data.startswith(b"\xff\xd8\xff")
    )
    return (str(media_type), data) if valid else (None, None)


async def _provider_response(
    provider: DeliverabilityProvider, raw: bytes, *, contract: str
) -> bytes:
    configured = str(provider.config_json.get("base_url", ""))
    parsed = urlsplit(configured)
    if parsed.scheme != "https" or not parsed.hostname or parsed.port not in {None, 443}:
        raise RuntimeError("Provider URL is not a supported HTTPS endpoint")
    addresses = await _public_addresses(parsed.hostname, 443)
    if not addresses:
        raise RuntimeError("Provider does not resolve exclusively to public addresses")
    address = ipaddress.ip_address(addresses[0])
    netloc = f"[{address}]" if address.version == 6 else str(address)
    pinned = urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))
    headers = {
        "Accept": "application/json",
        "Content-Type": "message/rfc822",
        "Host": parsed.hostname,
        "X-MailCue-Provider-Contract": contract,
    }
    if contract == "preview-v1":
        headers["X-MailCue-Preview-Contract"] = "1"
    if provider.secret_ciphertext:
        headers["Authorization"] = f"Bearer {decrypt_provider_secret(provider.secret_ciphertext)}"
    timeout = httpx.Timeout(settings.deliverability_network_timeout_seconds * 4)
    async with (
        httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client,
        client.stream(
            "POST",
            pinned,
            headers=headers,
            content=raw,
            extensions={"sni_hostname": parsed.hostname},
        ) as response,
    ):
        if response.status_code != 200:
            raise RuntimeError(f"Provider returned HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "").lower()
        if not content_type.startswith("application/json"):
            raise RuntimeError("Provider did not return JSON")
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > _MAX_PROVIDER_RESPONSE_BYTES:
                raise RuntimeError("Provider response exceeded the size limit")
            chunks.append(chunk)
    return b"".join(chunks)


async def run_preview_provider(
    provider: DeliverabilityProvider, raw: bytes
) -> list[PreviewResult]:
    payload_bytes = await _provider_response(provider, raw, contract="preview-v1")
    try:
        payload = json.loads(payload_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("Preview provider returned invalid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("previews"), list):
        raise RuntimeError("Preview provider response is missing previews")
    results: list[PreviewResult] = []
    for raw_item in payload["previews"][:_MAX_PREVIEWS]:
        if not isinstance(raw_item, dict):
            continue
        client = str(raw_item.get("client", "Unknown"))[:120]
        platform = str(raw_item.get("platform", "unknown"))[:80]
        theme = str(raw_item.get("theme", "default"))[:40]
        status = str(raw_item.get("status", "unknown"))[:40]
        description = str(raw_item.get("description", ""))[:1000]
        media_type, data = _decode_image(raw_item.get("image_base64"), raw_item.get("media_type"))
        results.append(
            PreviewResult(
                client=client,
                platform=platform,
                theme=theme,
                status=status,
                description=description,
                media_type=media_type,
                data=data,
            )
        )
    if not results:
        raise RuntimeError("Preview provider returned no usable preview results")
    return results


async def run_analysis_provider(
    provider: DeliverabilityProvider, raw: bytes
) -> AnalysisResult:
    payload_bytes = await _provider_response(provider, raw, contract="analysis-v1")
    try:
        payload = json.loads(payload_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("Analysis provider returned invalid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("findings"), list):
        raise RuntimeError("Analysis provider response is missing findings")
    findings: list[AnalysisFinding] = []
    for raw_item in payload["findings"][:100]:
        if not isinstance(raw_item, dict):
            continue
        findings.append(
            AnalysisFinding(
                severity=str(raw_item.get("severity", "info"))[:20].lower(),
                title=str(raw_item.get("title", "Finding"))[:160],
                detail=str(raw_item.get("detail", ""))[:2000],
                recommendation=str(raw_item.get("recommendation", ""))[:2000],
            )
        )
    return AnalysisResult(summary=str(payload.get("summary", ""))[:2000], findings=findings)
