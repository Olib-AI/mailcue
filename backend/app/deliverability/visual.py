"""Network-blocked local Chromium renders for email visual inspection."""

from __future__ import annotations

import asyncio
import os
import pwd
import shutil
import signal
import tempfile
from dataclasses import dataclass
from email import message_from_bytes, policy
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps, ImageStat

from app.config import settings

_CSP = (
    "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; "
    "connect-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; "
    "form-action 'none'; base-uri 'none'"
)


@dataclass(frozen=True)
class RenderedArtifact:
    name: str
    width: int
    height: int
    data: bytes


def attention_estimate(screenshot: bytes) -> bytes:
    """Create a deterministic visual-saliency aid without claiming eye tracking."""
    with Image.open(BytesIO(screenshot)) as source:
        image = source.convert("RGB")
        luminance = ImageOps.grayscale(image)
        edges = luminance.filter(ImageFilter.FIND_EDGES)
        contrast = ImageChops.difference(
            luminance, luminance.filter(ImageFilter.GaussianBlur(radius=12))
        )
        saliency = ImageChops.lighter(edges, contrast)
        saliency = ImageEnhance.Contrast(ImageOps.autocontrast(saliency)).enhance(1.8)
        saliency = saliency.filter(ImageFilter.GaussianBlur(radius=7))
        heat = ImageOps.colorize(
            saliency,
            black="#14315c",
            mid="#ffd166",
            white="#ef476f",
        )
        composite = Image.blend(image, heat, 0.52)
        output = BytesIO()
        composite.save(output, format="PNG", optimize=True)
        return output.getvalue()


def image_difference_percent(before: bytes, after: bytes) -> float:
    """Return normalized RGB pixel difference, resizing only for a stable comparison canvas."""
    with Image.open(BytesIO(before)) as before_image, Image.open(BytesIO(after)) as after_image:
        left = before_image.convert("RGB")
        right = after_image.convert("RGB")
        if left.size != right.size:
            right = right.resize(left.size)
        difference = ImageChops.difference(left, right)
        mean = ImageStat.Stat(difference).mean
    return round(sum(mean) / (len(mean) * 255) * 100, 2)


def chromium_executable() -> str | None:
    configured = settings.deliverability_chromium_path.strip()
    if not configured:
        return None
    return shutil.which(configured)


def _html_body(raw: bytes) -> str:
    parsed = message_from_bytes(raw, policy=policy.default)
    if not isinstance(parsed, EmailMessage):
        return ""
    for part in parsed.walk():
        if (
            part.get_content_type() != "text/html"
            or part.get_content_disposition() == "attachment"
        ):
            continue
        try:
            return str(part.get_content())[:2_000_000]
        except (LookupError, UnicodeError):
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                return payload.decode("utf-8", errors="replace")[:2_000_000]
    return ""


def _document(body: str) -> str:
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{_CSP}">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<style>html{color-scheme:light dark}body{margin:0;overflow-wrap:anywhere}</style>"
        f"</head><body>{body}</body></html>"
    )


async def _render_one(
    executable: str,
    directory: Path,
    html_path: Path,
    *,
    name: str,
    width: int,
    height: int,
    dark: bool,
    renderer_identity: tuple[int, int] | None,
) -> RenderedArtifact:
    output = directory / f"{name}.png"
    args = [
        executable,
        "--headless=new",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-features=NetworkServiceInProcess",
        "--disable-sync",
        "--hide-scrollbars",
        "--host-resolver-rules=MAP * ~NOTFOUND",
        "--no-first-run",
        "--no-proxy-server",
        "--no-sandbox",
        f"--screenshot={output}",
        f"--window-size={width},{height}",
    ]
    if dark:
        args.append("--force-dark-mode")
    args.append(html_path.as_uri())
    environment = {**os.environ, "HOME": str(directory)}

    def drop_renderer_privileges() -> None:
        if renderer_identity is None:
            return
        uid, gid = renderer_identity
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)

    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
        preexec_fn=drop_renderer_privileges if renderer_identity else None,
        start_new_session=True,
    )
    try:
        _stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=settings.deliverability_visual_timeout_seconds
        )
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
        await process.wait()
        raise RuntimeError("Chromium render timed out") from None
    except asyncio.CancelledError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
        await process.wait()
        raise
    if process.returncode != 0 or not output.is_file():
        detail = stderr.decode("utf-8", errors="replace")[-500:].strip()
        raise RuntimeError(f"Chromium render failed: {detail or process.returncode}")
    data = output.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("Chromium did not produce a valid PNG")
    if len(data) > settings.deliverability_artifact_max_bytes:
        raise RuntimeError("Rendered screenshot exceeds the configured artifact limit")
    return RenderedArtifact(name=name, width=width, height=height, data=data)


async def render_email(raw: bytes) -> list[RenderedArtifact]:
    executable = chromium_executable()
    if executable is None:
        raise RuntimeError("Chromium is not installed")
    body = _html_body(raw)
    if not body:
        return []
    with tempfile.TemporaryDirectory(prefix="mailcue-render-") as temporary:
        directory = Path(temporary)
        html_path = directory / "message.html"
        html_path.write_text(_document(body), encoding="utf-8")
        renderer_identity: tuple[int, int] | None = None
        if os.geteuid() == 0:
            account = pwd.getpwnam("nobody")
            renderer_identity = (account.pw_uid, account.pw_gid)
            os.chown(directory, account.pw_uid, account.pw_gid)
            os.chown(html_path, account.pw_uid, account.pw_gid)
        variants = (
            ("desktop-light", 1200, 900, False),
            ("desktop-dark", 1200, 900, True),
            ("tablet-light", 768, 1024, False),
            ("tablet-dark", 768, 1024, True),
            ("mobile-light", 390, 844, False),
            ("mobile-dark", 390, 844, True),
        )
        artifacts: list[RenderedArtifact] = []
        for name, width, height, dark in variants:
            artifacts.append(
                await _render_one(
                    executable,
                    directory,
                    html_path,
                    name=name,
                    width=width,
                    height=height,
                    dark=dark,
                    renderer_identity=renderer_identity,
                )
            )
        for source in [item for item in artifacts if item.name.endswith("-light")]:
            estimate = attention_estimate(source.data)
            if len(estimate) > settings.deliverability_artifact_max_bytes:
                raise RuntimeError("Attention estimate exceeds the configured artifact limit")
            artifacts.append(
                RenderedArtifact(
                    name=f"attention-{source.name.removesuffix('-light')}",
                    width=source.width,
                    height=source.height,
                    data=estimate,
                )
            )
        return artifacts
