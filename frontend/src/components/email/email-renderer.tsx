import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import DOMPurify from "dompurify";
import { getAccessToken } from "@/lib/api";
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

interface FrameMessage {
  type: "mailcue:render-email";
  html: string;
  isDark: boolean;
}

function sanitizeEmailHtml(html: string): string {
  const clean = DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    ADD_ATTR: ["target"],
    FORBID_TAGS: ["script", "object", "embed", "iframe", "form", "base"],
    FORBID_ATTR: ["formaction", "ping"],
    ALLOW_DATA_ATTR: false,
  });
  return clean.replace(
    /<a\s/gi,
    '<a target="_blank" rel="noopener noreferrer" ',
  );
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () =>
      reject(reader.error ?? new Error("Unable to read image"));
    reader.readAsDataURL(blob);
  });
}

async function resolveCidReferences(
  html: string,
  mailbox: string,
  uid: string,
  attachments: EmailAttachment[],
  signal: AbortSignal,
): Promise<string> {
  let resolved = html;
  const token = getAccessToken();

  await Promise.all(
    attachments.map(async (attachment) => {
      if (!attachment.content_id) return;

      const url = `/api/v1/emails/${encodeURIComponent(uid)}/attachments/${encodeURIComponent(
        attachment.part_id,
      )}?mailbox=${encodeURIComponent(mailbox)}`;
      const response = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: "include",
        signal,
      });
      if (!response.ok) return;

      const dataUrl = await blobToDataUrl(await response.blob());
      const cid = attachment.content_id.replace(/^<|>$/g, "");
      const escaped = cid.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      resolved = resolved.replace(new RegExp(`cid:${escaped}`, "gi"), dataUrl);
    }),
  );

  return resolved;
}

/** Render untrusted email HTML in a separately secured document. */
function EmailRenderer({ html, mailbox, uid, attachments }: EmailRendererProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(300);
  const [resolvedCidHtml, setResolvedCidHtml] = useState<{
    source: string;
    value: string;
  } | null>(null);
  const isDark =
    typeof document !== "undefined" &&
    document.documentElement.classList.contains("dark");

  useEffect(() => {
    const controller = new AbortController();

    if (
      mailbox &&
      uid &&
      attachments?.some((attachment) => attachment.content_id)
    ) {
      void resolveCidReferences(html, mailbox, uid, attachments, controller.signal)
        .then((value) => setResolvedCidHtml({ source: html, value }))
        .catch(() => undefined);
    }

    return () => controller.abort();
  }, [html, mailbox, uid, attachments]);

  const resolvedHtml =
    resolvedCidHtml?.source === html ? resolvedCidHtml.value : html;
  const sanitizedHtml = useMemo(
    () => sanitizeEmailHtml(resolvedHtml),
    [resolvedHtml],
  );

  const renderFrame = useCallback(() => {
    const message: FrameMessage = {
      type: "mailcue:render-email",
      html: sanitizedHtml,
      isDark,
    };
    iframeRef.current?.contentWindow?.postMessage(message, "*");
  }, [sanitizedHtml, isDark]);

  useEffect(renderFrame, [renderFrame]);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as { type?: string; height?: number } | undefined;
      if (data?.type === "mailcue:email-height" && typeof data.height === "number") {
        const newHeight = Math.max(300, Math.ceil(data.height));
        setHeight((previous) =>
          Math.abs(previous - newHeight) > 1 ? newHeight : previous,
        );
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  return (
    <iframe
      ref={iframeRef}
      title="Email content"
      sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
      referrerPolicy="no-referrer"
      src="/email-frame.html"
      onLoad={renderFrame}
      className="email-iframe w-full rounded border-0"
      style={{ height }}
    />
  );
}

export { EmailRenderer };
