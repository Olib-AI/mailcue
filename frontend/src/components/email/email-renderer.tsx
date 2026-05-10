import { useEffect, useMemo, useRef, useState } from "react";
import DOMPurify from "dompurify";
import type { EmailAttachment } from "@/types/api";

interface EmailRendererProps {
  html: string;
  /** Mailbox address for resolving CID inline image URLs. */
  mailbox?: string;
  /** Email UID for resolving CID inline image URLs. */
  uid?: string;
  /** Attachments containing content_id mappings for CID resolution. */
  attachments?: EmailAttachment[];
}

/**
 * Sandboxed HTML email viewer.
 *
 * Why this is more involved than a plain ``<iframe srcdoc>``:
 *
 *   1. The host application sets a strict CSP that — by design — blocks
 *      remote images, fonts, and stylesheets.  Real-world email relies on
 *      all three, so we have to render it under a *different* policy than
 *      the rest of the app.
 *   2. We do that by giving the email frame a **null origin** (sandbox
 *      without ``allow-same-origin``).  In a null-origin frame the host's
 *      page-level CSP does not apply to subresources, so we can attach a
 *      per-frame ``<meta http-equiv="Content-Security-Policy">`` that
 *      reflects what email actually needs (images/CSS/fonts permitted,
 *      scripts/forms/objects/frames denied).
 *   3. Because the frame is cross-origin from the parent we can no longer
 *      reach into ``iframe.contentDocument``.  Auto-resize is therefore
 *      done by a tiny inline script that posts the body height back to
 *      the parent.  CSP whitelists exactly that script via a SHA-256 hash
 *      so DOMPurify's strip-script guarantee remains the only path for
 *      email content to ever execute JS — i.e. it cannot.
 */

const RESIZE_SCRIPT = `(function(){
function send(){
  try {
    var h = Math.max(
      document.body ? document.body.scrollHeight : 0,
      document.documentElement ? document.documentElement.scrollHeight : 0
    );
    parent.postMessage({type:'mailcue:email-height', height: h}, '*');
  } catch (e) {}
}
if (document.readyState === 'complete') send();
else window.addEventListener('load', send);
window.addEventListener('resize', send);
new MutationObserver(send).observe(document.documentElement, {childList:true,subtree:true,attributes:true});
Array.prototype.forEach.call(document.images || [], function(img){ img.addEventListener('load', send); img.addEventListener('error', send); });
})();`;

// Pre-computed SHA-256 of RESIZE_SCRIPT (base64).  Recompute if the script
// body changes — `crypto.subtle.digest('SHA-256', utf8(RESIZE_SCRIPT))` →
// base64.  Hardcoding it keeps the CSP literal, so a tampered build doesn't
// silently widen the policy.
const RESIZE_SCRIPT_SHA256 = "h3L+pxCOh+5xcqs/mZoaIfVeVafcPPl3jmt9F60KCQk=";

const FRAME_CSP = [
  "default-src 'none'",
  // ``cid:`` URLs were rewritten to ``/api/...`` paths upstream; ``data:``
  // covers inline base64; ``https:`` covers remote images on properly-
  // hosted CDNs.  ``http:`` is intentionally included so legacy emails
  // still attempt the load — the browser's mixed-content policy is the
  // backstop on an HTTPS host.
  "img-src 'self' https: http: data: blob:",
  "style-src 'unsafe-inline' https: data:",
  "font-src 'self' https: data:",
  "media-src 'self' https: data: blob:",
  `script-src 'sha256-${RESIZE_SCRIPT_SHA256}'`,
  "object-src 'none'",
  "frame-src 'none'",
  "child-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
  "connect-src 'none'",
].join("; ");

function buildSrcdoc(sanitizedHtml: string, isDark: boolean): string {
  const fg = isDark ? "#e5e7eb" : "#1f2937";
  const bg = isDark ? "#1f2937" : "#ffffff";
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="${FRAME_CSP}">
<style>
  html, body { margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    color: ${fg};
    background: ${bg};
    padding: 16px;
    word-wrap: break-word;
    overflow-wrap: break-word;
  }
  img { max-width: 100%; height: auto; }
  a { color: #3b82f6; }
  table { max-width: 100%; }
  pre, code { white-space: pre-wrap; word-wrap: break-word; }
</style>
</head>
<body>${sanitizedHtml}
<script>${RESIZE_SCRIPT}</script>
</body>
</html>`;
}

function rewriteCidReferences(
  html: string,
  mailbox: string | undefined,
  uid: string | undefined,
  attachments: EmailAttachment[] | undefined,
): string {
  if (!mailbox || !uid || !attachments) return html;
  let out = html;
  for (const att of attachments) {
    if (!att.content_id) continue;
    const cid = att.content_id.replace(/^<|>$/g, "");
    const escaped = cid.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const url = `/api/v1/mailboxes/${encodeURIComponent(
      mailbox,
    )}/emails/${uid}/attachments/${att.part_id}`;
    out = out.replace(new RegExp(`cid:${escaped}`, "gi"), url);
  }
  return out;
}

function EmailRenderer({ html, mailbox, uid, attachments }: EmailRendererProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState<number>(200);
  const isDark =
    typeof document !== "undefined" &&
    document.documentElement.classList.contains("dark");

  const srcdoc = useMemo(() => {
    const withCids = rewriteCidReferences(html, mailbox, uid, attachments);
    const clean = DOMPurify.sanitize(withCids, {
      USE_PROFILES: { html: true },
      ADD_ATTR: ["target"],
      FORBID_TAGS: ["script", "object", "embed", "iframe", "form", "base"],
      FORBID_ATTR: ["formaction", "ping"],
      ALLOW_DATA_ATTR: false,
    });
    const withTargets = clean.replace(
      /<a\s/gi,
      '<a target="_blank" rel="noopener noreferrer" ',
    );
    return buildSrcdoc(withTargets, isDark);
  }, [html, mailbox, uid, attachments, isDark]);

  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      if (ev.source !== iframeRef.current?.contentWindow) return;
      const data = ev.data as { type?: string; height?: number } | undefined;
      if (data?.type === "mailcue:email-height" && typeof data.height === "number") {
        setHeight(Math.max(200, Math.ceil(data.height) + 32));
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  return (
    <iframe
      ref={iframeRef}
      title="Email content"
      // No ``allow-same-origin`` → null origin → host-page CSP does not
      // restrict subresource loads inside the frame; the meta CSP in the
      // srcdoc owns that policy.  ``allow-popups`` lets target=_blank
      // links open in a new tab; ``allow-popups-to-escape-sandbox`` lets
      // the resulting tab function normally.
      sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
      referrerPolicy="no-referrer"
      srcDoc={srcdoc}
      className="email-iframe w-full rounded border-0"
      style={{ height }}
    />
  );
}

export { EmailRenderer };
