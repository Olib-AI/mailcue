import { useRef, useEffect, useCallback } from "react";
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
 * Renders sanitized HTML email content inside a sandboxed iframe.
 * - Replaces cid: references with attachment download URLs
 * - Sanitizes HTML with DOMPurify (strips scripts, event handlers)
 * - Isolates email styles from the app via iframe sandboxing
 */
function EmailRenderer({ html, mailbox, uid, attachments }: EmailRendererProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const writeToIframe = useCallback(
    (sanitizedHtml: string) => {
      const iframe = iframeRef.current;
      if (!iframe) return;

      const doc = iframe.contentDocument;
      if (!doc) return;

      // Detect current theme
      const isDark = document.documentElement.classList.contains("dark");

      const wrappedHtml = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 14px;
      line-height: 1.6;
      color: ${isDark ? "#e5e7eb" : "#1f2937"};
      background: ${isDark ? "#1f2937" : "#ffffff"};
      margin: 0;
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
<body>${sanitizedHtml}</body>
</html>`;

      doc.open();
      doc.write(wrappedHtml);
      doc.close();

      // Auto-resize iframe to content height
      const resizeObserver = new ResizeObserver(() => {
        const body = iframe.contentDocument?.body;
        if (body) {
          iframe.style.height = `${body.scrollHeight + 32}px`;
        }
      });

      if (iframe.contentDocument?.body) {
        resizeObserver.observe(iframe.contentDocument.body);
      }
    },
    []
  );

  useEffect(() => {
    // Replace cid: references with actual attachment download URLs before
    // sanitization so DOMPurify sees valid /api/... paths and keeps them.
    let processedHtml = html;
    if (mailbox && uid && attachments) {
      attachments.forEach((att) => {
        if (att.content_id) {
          const cidUrl = `/api/v1/mailboxes/${encodeURIComponent(mailbox)}/emails/${uid}/attachments/${att.part_id}`;
          const cid = att.content_id.replace(/^<|>$/g, "");
          const escaped = cid.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          processedHtml = processedHtml.replace(
            new RegExp(`cid:${escaped}`, "gi"),
            cidUrl
          );
        }
      });
    }

    // Sanitize with DOMPurify
    const clean = DOMPurify.sanitize(processedHtml, {
      USE_PROFILES: { html: true },
      ADD_ATTR: ["target"],
      FORBID_TAGS: [],
      ALLOW_DATA_ATTR: false,
    });

    // Open all links in a new tab
    const withTargets = clean.replace(
      /<a\s/gi,
      '<a target="_blank" rel="noopener noreferrer" '
    );

    writeToIframe(withTargets);
  }, [html, mailbox, uid, attachments, writeToIframe]);

  return (
    <iframe
      ref={iframeRef}
      title="Email content"
      sandbox="allow-same-origin"
      className="email-iframe w-full rounded border-0"
      style={{ minHeight: 200 }}
    />
  );
}

export { EmailRenderer };
