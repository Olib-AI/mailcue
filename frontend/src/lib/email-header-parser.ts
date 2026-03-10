// =============================================================================
// Email Header Parsing Utilities
// Extracts structured authentication, routing, security, and threading data
// from raw email headers. All parsers are resilient to malformed input.
// =============================================================================

// --- Types ---

export type AuthResult = "pass" | "fail" | "softfail" | "neutral" | "none" | "temperror" | "permerror" | "policy" | "unknown";

export interface SpfResult {
  result: AuthResult;
  domain: string | null;
  ip: string | null;
  detail: string | null;
}

export interface DkimResult {
  result: AuthResult;
  domain: string | null;
  selector: string | null;
  detail: string | null;
}

export interface DmarcResult {
  result: AuthResult;
  policy: string | null;
  domain: string | null;
  detail: string | null;
}

export interface AuthenticationResults {
  server: string | null;
  spf: SpfResult | null;
  dkim: DkimResult[];
  dmarc: DmarcResult | null;
  raw: string;
}

export interface MailHop {
  index: number;
  from: string | null;
  by: string | null;
  ip: string | null;
  protocol: string | null;
  timestamp: Date | null;
  tls: boolean;
  raw: string;
}

export interface MailRoute {
  hops: MailHop[];
}

export interface SecurityHeaders {
  arcSeal: string | null;
  arcMessageSignature: string | null;
  arcAuthenticationResults: string | null;
  dkimSignature: DkimSignatureInfo | null;
  returnPath: string | null;
  receivedSpf: string | null;
  tlsInfo: string[];
}

export interface DkimSignatureInfo {
  algorithm: string | null;
  selector: string | null;
  domain: string | null;
  raw: string;
}

export interface ThreadingInfo {
  messageId: string | null;
  inReplyTo: string | null;
  references: string[];
}

// --- Helpers ---

function normalizeResult(raw: string): AuthResult {
  const lower = raw.toLowerCase().trim();
  const valid: AuthResult[] = ["pass", "fail", "softfail", "neutral", "none", "temperror", "permerror", "policy"];
  return (valid.find((v) => v === lower) ?? "unknown") as AuthResult;
}

function extractProperty(text: string, key: string): string | null {
  // Matches key=value or key="value" patterns
  const regex = new RegExp(`${key}\\s*=\\s*(?:"([^"]*)"|(\\S+))`, "i");
  const match = text.match(regex);
  return match?.[1] ?? match?.[2] ?? null;
}

function extractParenContent(text: string): string | null {
  const match = text.match(/\(([^)]+)\)/);
  return match?.[1] ?? null;
}

// --- Parsers ---

export function parseAuthenticationResults(headers: Record<string, string>): AuthenticationResults | null {
  const raw = headers["Authentication-Results"] ?? headers["authentication-results"];
  if (!raw) return null;

  // Server is the first token before the first semicolon
  const serverMatch = raw.match(/^\s*([^;]+)/);
  const server = serverMatch?.[1]?.trim() ?? null;

  // Split on semicolons for individual results
  const parts = raw.split(";").slice(1);

  let spf: SpfResult | null = null;
  const dkim: DkimResult[] = [];
  let dmarc: DmarcResult | null = null;

  for (const part of parts) {
    const trimmed = part.trim();
    if (!trimmed) continue;

    if (/^\s*spf\s*=/i.test(trimmed)) {
      const resultMatch = trimmed.match(/spf\s*=\s*(\S+)/i);
      spf = {
        result: normalizeResult(resultMatch?.[1] ?? "unknown"),
        domain: extractProperty(trimmed, "smtp.mailfrom") ?? extractProperty(trimmed, "smtp.helo"),
        ip: null,
        detail: extractParenContent(trimmed),
      };
    } else if (/^\s*dkim\s*=/i.test(trimmed)) {
      const resultMatch = trimmed.match(/dkim\s*=\s*(\S+)/i);
      dkim.push({
        result: normalizeResult(resultMatch?.[1] ?? "unknown"),
        domain: extractProperty(trimmed, "header.d"),
        selector: extractProperty(trimmed, "header.s"),
        detail: extractParenContent(trimmed),
      });
    } else if (/^\s*dmarc\s*=/i.test(trimmed)) {
      const resultMatch = trimmed.match(/dmarc\s*=\s*(\S+)/i);
      dmarc = {
        result: normalizeResult(resultMatch?.[1] ?? "unknown"),
        policy: extractProperty(trimmed, "p") ?? extractProperty(trimmed, "policy"),
        domain: extractProperty(trimmed, "header.from"),
        detail: extractParenContent(trimmed),
      };
    }
  }

  return { server, spf, dkim, dmarc, raw };
}

export function parseReceivedHeaders(headers: Record<string, string>): MailRoute {
  // Received headers may be a single string with multiple values joined by newlines,
  // or a single value. We also check numbered variants.
  const receivedValues: string[] = [];

  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === "received") {
      // Could be multiple values joined by the backend
      receivedValues.push(...value.split(/\n(?=from |by )/i));
    }
  }

  const hops: MailHop[] = receivedValues.map((raw, index) => {
    const fromMatch = raw.match(/from\s+(\S+)/i);
    const byMatch = raw.match(/by\s+(\S+)/i);
    const ipMatch = raw.match(/\[(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\]/);
    const ipv6Match = !ipMatch ? raw.match(/\[(?:IPv6:)?([a-fA-F0-9:]+)\]/i) : null;
    const protocolMatch = raw.match(/with\s+(E?SMTPS?A?)\b/i);
    const tls = /\bTLS\b|ESMTPS/i.test(raw);

    // Try to extract date from the end of the Received header (after the last semicolon)
    let timestamp: Date | null = null;
    const datePart = raw.split(";").pop();
    if (datePart) {
      const parsed = new Date(datePart.trim());
      if (!isNaN(parsed.getTime())) {
        timestamp = parsed;
      }
    }

    return {
      index,
      from: fromMatch?.[1] ?? null,
      by: byMatch?.[1] ?? null,
      ip: ipMatch?.[1] ?? ipv6Match?.[1] ?? null,
      protocol: protocolMatch?.[1]?.toUpperCase() ?? null,
      timestamp,
      tls,
      raw: raw.trim(),
    };
  });

  return { hops };
}

export function parseSecurityHeaders(headers: Record<string, string>): SecurityHeaders {
  const getHeader = (name: string): string | null => {
    // Case-insensitive lookup
    for (const [key, value] of Object.entries(headers)) {
      if (key.toLowerCase() === name.toLowerCase()) return value;
    }
    return null;
  };

  // Parse DKIM-Signature
  let dkimSignature: DkimSignatureInfo | null = null;
  const dkimSigRaw = getHeader("DKIM-Signature");
  if (dkimSigRaw) {
    dkimSignature = {
      algorithm: extractProperty(dkimSigRaw, "a"),
      selector: extractProperty(dkimSigRaw, "s"),
      domain: extractProperty(dkimSigRaw, "d"),
      raw: dkimSigRaw,
    };
  }

  // Extract TLS info from Received headers
  const tlsInfo: string[] = [];
  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === "received") {
      const tlsMatch = value.match(/\(.*?TLS[^)]*\)/gi);
      if (tlsMatch) {
        tlsInfo.push(...tlsMatch.map((m) => m.replace(/^\(|\)$/g, "")));
      }
    }
  }

  return {
    arcSeal: getHeader("ARC-Seal"),
    arcMessageSignature: getHeader("ARC-Message-Signature"),
    arcAuthenticationResults: getHeader("ARC-Authentication-Results"),
    dkimSignature,
    returnPath: getHeader("Return-Path"),
    receivedSpf: getHeader("Received-SPF"),
    tlsInfo,
  };
}

export function parseThreadingInfo(headers: Record<string, string>): ThreadingInfo {
  const getHeader = (name: string): string | null => {
    for (const [key, value] of Object.entries(headers)) {
      if (key.toLowerCase() === name.toLowerCase()) return value;
    }
    return null;
  };

  const referencesRaw = getHeader("References");
  const references: string[] = referencesRaw
    ? referencesRaw.match(/<[^>]+>/g)?.map((r) => r) ?? []
    : [];

  return {
    messageId: getHeader("Message-ID") ?? getHeader("Message-Id"),
    inReplyTo: getHeader("In-Reply-To"),
    references,
  };
}
