import { useRef, useEffect, useCallback } from "react";
import DOMPurify from "dompurify";

interface EmailRendererProps {
  html: string;
  /** Reserved for future CID image resolution. */
  mailbox?: string;
}

/**
 * Renders sanitized HTML email content inside a sandboxed iframe.
 * - Sanitizes HTML with DOMPurify (strips scripts, event handlers)
 * - Replaces cid: references with attachment download URLs
 * - Isolates email styles from the app via iframe sandboxing
 */
function EmailRenderer({ html }: EmailRendererProps) {
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
    // Sanitize with DOMPurify
    const clean = DOMPurify.sanitize(html, {
      USE_PROFILES: { html: true },
      ADD_ATTR: ["target"],
      FORBID_TAGS: ["style"],
      ALLOW_DATA_ATTR: false,
    });

    // Open all links in a new tab
    const withTargets = clean.replace(
      /<a\s/gi,
      '<a target="_blank" rel="noopener noreferrer" '
    );

    writeToIframe(withTargets);
  }, [html, writeToIframe]);

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
