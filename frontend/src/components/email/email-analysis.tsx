import { useMemo } from "react";
import {
  Shield,
  ShieldCheck,
  ShieldX,
  ShieldAlert,
  Route,
  Lock,
  MessageSquare,
  Clock,
  Server,
  ArrowDown,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import {
  parseAuthenticationResults,
  parseReceivedHeaders,
  parseSecurityHeaders,
  parseThreadingInfo,
} from "@/lib/email-header-parser";
import type {
  AuthResult,
  AuthenticationResults,
  MailRoute,
  MailHop,
  SecurityHeaders,
  ThreadingInfo,
} from "@/lib/email-header-parser";

// --- Props ---

interface EmailAnalysisProps {
  headers: Record<string, string>;
}

// --- Badge helpers ---

function resultBadgeClass(result: AuthResult): string {
  switch (result) {
    case "pass":
      return "bg-green-100 text-green-800 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800";
    case "fail":
    case "permerror":
      return "bg-red-100 text-red-800 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800";
    case "softfail":
    case "temperror":
    case "policy":
      return "bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-400 dark:border-yellow-800";
    case "neutral":
    case "none":
    case "unknown":
    default:
      return "bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800/50 dark:text-gray-400 dark:border-gray-700";
  }
}

function ResultBadge({ result }: { result: AuthResult }) {
  return (
    <Badge variant="outline" className={cn("font-mono text-xs", resultBadgeClass(result))}>
      {result}
    </Badge>
  );
}

function resultIcon(result: AuthResult) {
  switch (result) {
    case "pass":
      return <ShieldCheck className="h-4 w-4 text-green-600 dark:text-green-400" />;
    case "fail":
    case "permerror":
      return <ShieldX className="h-4 w-4 text-red-600 dark:text-red-400" />;
    case "softfail":
    case "temperror":
    case "policy":
      return <ShieldAlert className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />;
    default:
      return <Shield className="h-4 w-4 text-gray-500" />;
  }
}

// --- Section Components ---

function AuthenticationResultsPanel({ auth }: { auth: AuthenticationResults }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <ShieldCheck className="h-4 w-4" />
          Authentication Results
        </CardTitle>
        {auth.server && (
          <p className="text-xs text-muted-foreground">
            Checked by: {auth.server}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {/* SPF */}
        {auth.spf && (
          <div className="flex items-start gap-3 rounded-md border p-3">
            {resultIcon(auth.spf.result)}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-medium">SPF</span>
                <ResultBadge result={auth.spf.result} />
              </div>
              {auth.spf.domain && (
                <p className="text-xs text-muted-foreground font-mono truncate">
                  Domain: {auth.spf.domain}
                </p>
              )}
              {auth.spf.detail && (
                <p className="text-xs text-muted-foreground mt-0.5">{auth.spf.detail}</p>
              )}
            </div>
          </div>
        )}

        {/* DKIM */}
        {auth.dkim.map((dkimResult, i) => (
          <div key={`dkim-${i}`} className="flex items-start gap-3 rounded-md border p-3">
            {resultIcon(dkimResult.result)}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-medium">DKIM</span>
                <ResultBadge result={dkimResult.result} />
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-0.5">
                {dkimResult.domain && (
                  <p className="text-xs text-muted-foreground font-mono">
                    Domain: {dkimResult.domain}
                  </p>
                )}
                {dkimResult.selector && (
                  <p className="text-xs text-muted-foreground font-mono">
                    Selector: {dkimResult.selector}
                  </p>
                )}
              </div>
              {dkimResult.detail && (
                <p className="text-xs text-muted-foreground mt-0.5">{dkimResult.detail}</p>
              )}
            </div>
          </div>
        ))}

        {/* DMARC */}
        {auth.dmarc && (
          <div className="flex items-start gap-3 rounded-md border p-3">
            {resultIcon(auth.dmarc.result)}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-medium">DMARC</span>
                <ResultBadge result={auth.dmarc.result} />
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-0.5">
                {auth.dmarc.domain && (
                  <p className="text-xs text-muted-foreground font-mono">
                    Domain: {auth.dmarc.domain}
                  </p>
                )}
                {auth.dmarc.policy && (
                  <p className="text-xs text-muted-foreground font-mono">
                    Policy: {auth.dmarc.policy}
                  </p>
                )}
              </div>
              {auth.dmarc.detail && (
                <p className="text-xs text-muted-foreground mt-0.5">{auth.dmarc.detail}</p>
              )}
            </div>
          </div>
        )}

        {!auth.spf && auth.dkim.length === 0 && !auth.dmarc && (
          <p className="text-xs text-muted-foreground">
            No authentication results could be parsed from the header.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function formatHopTimestamp(date: Date): string {
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
    timeZoneName: "short",
  });
}

function formatDelta(ms: number): string {
  if (ms < 0) return "clock skew";
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  return `${hours}h`;
}

function HopCard({ hop, delta }: { hop: MailHop; delta: string | null }) {
  return (
    <div className="rounded-md border p-3">
      <div className="flex items-center gap-2 mb-1.5">
        <Server className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        <span className="text-xs font-medium truncate">
          {hop.by ?? hop.from ?? "Unknown server"}
        </span>
        {hop.protocol && (
          <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0", hop.tls && "border-green-300 text-green-700 dark:border-green-700 dark:text-green-400")}>
            {hop.protocol}
            {hop.tls && " (TLS)"}
          </Badge>
        )}
      </div>
      <div className="grid gap-0.5 text-xs text-muted-foreground pl-5.5">
        {hop.from && hop.from !== hop.by && (
          <span className="font-mono truncate">From: {hop.from}</span>
        )}
        {hop.ip && (
          <span className="font-mono">IP: {hop.ip}</span>
        )}
        {hop.timestamp && (
          <div className="flex items-center gap-1.5">
            <Clock className="h-3 w-3 shrink-0" />
            <span>{formatHopTimestamp(hop.timestamp)}</span>
            {delta && (
              <Badge variant="outline" className="text-[10px] px-1 py-0 ml-1">
                +{delta}
              </Badge>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function RoutingAnalysis({ route }: { route: MailRoute }) {
  if (route.hops.length === 0) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Route className="h-4 w-4" />
            Routing Analysis
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">No Received headers found.</p>
        </CardContent>
      </Card>
    );
  }

  // Received headers are in reverse chronological order (newest first).
  // Reverse them so the timeline shows origin -> destination.
  const orderedHops = [...route.hops].reverse();

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Route className="h-4 w-4" />
          Routing Analysis
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          {route.hops.length} hop{route.hops.length !== 1 ? "s" : ""} from origin to destination
        </p>
      </CardHeader>
      <CardContent>
        <div className="space-y-0">
          {orderedHops.map((hop, i) => {
            // Calculate time delta from previous hop
            let delta: string | null = null;
            if (i > 0) {
              const prev = orderedHops[i - 1];
              if (prev?.timestamp && hop.timestamp) {
                const ms = hop.timestamp.getTime() - prev.timestamp.getTime();
                delta = formatDelta(ms);
              }
            }

            return (
              <div key={hop.index}>
                {i > 0 && (
                  <div className="flex justify-center py-1">
                    <ArrowDown className="h-3.5 w-3.5 text-muted-foreground/50" />
                  </div>
                )}
                <HopCard hop={hop} delta={delta} />
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function SecurityHeadersPanel({ security }: { security: SecurityHeaders }) {
  const hasAny =
    security.arcSeal ||
    security.arcMessageSignature ||
    security.arcAuthenticationResults ||
    security.dkimSignature ||
    security.returnPath ||
    security.receivedSpf ||
    security.tlsInfo.length > 0;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Lock className="h-4 w-4" />
          Security Headers
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!hasAny ? (
          <p className="text-xs text-muted-foreground">No security-related headers found.</p>
        ) : (
          <div className="space-y-2.5">
            {/* Return-Path */}
            {security.returnPath && (
              <HeaderRow label="Return-Path" value={security.returnPath} />
            )}

            {/* Received-SPF */}
            {security.receivedSpf && (
              <HeaderRow label="Received-SPF" value={security.receivedSpf} />
            )}

            {/* DKIM-Signature */}
            {security.dkimSignature && (
              <div className="space-y-1">
                <span className="text-xs font-medium text-muted-foreground">DKIM-Signature</span>
                <div className="flex flex-wrap gap-1.5">
                  {security.dkimSignature.algorithm && (
                    <Badge variant="outline" className="text-xs font-mono">
                      Algorithm: {security.dkimSignature.algorithm}
                    </Badge>
                  )}
                  {security.dkimSignature.selector && (
                    <Badge variant="outline" className="text-xs font-mono">
                      Selector: {security.dkimSignature.selector}
                    </Badge>
                  )}
                  {security.dkimSignature.domain && (
                    <Badge variant="outline" className="text-xs font-mono">
                      Domain: {security.dkimSignature.domain}
                    </Badge>
                  )}
                </div>
              </div>
            )}

            {/* ARC Headers */}
            {(security.arcSeal || security.arcMessageSignature || security.arcAuthenticationResults) && (
              <>
                <Separator />
                <span className="text-xs font-medium text-muted-foreground block">ARC Headers</span>
                <div className="space-y-1">
                  <PresenceIndicator label="ARC-Seal" present={!!security.arcSeal} />
                  <PresenceIndicator label="ARC-Message-Signature" present={!!security.arcMessageSignature} />
                  <PresenceIndicator label="ARC-Authentication-Results" present={!!security.arcAuthenticationResults} />
                </div>
              </>
            )}

            {/* TLS Info */}
            {security.tlsInfo.length > 0 && (
              <>
                <Separator />
                <span className="text-xs font-medium text-muted-foreground block">TLS Information</span>
                {security.tlsInfo.map((info, i) => (
                  <p key={i} className="text-xs font-mono text-muted-foreground break-all">
                    {info}
                  </p>
                ))}
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function HeaderRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <p className="text-xs font-mono break-all">{value}</p>
    </div>
  );
}

function PresenceIndicator({ label, present }: { label: string; present: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <div
        className={cn(
          "h-2 w-2 rounded-full",
          present ? "bg-green-500" : "bg-gray-300 dark:bg-gray-600"
        )}
      />
      <span className="text-xs font-mono">{label}</span>
      <span className="text-xs text-muted-foreground">
        {present ? "Present" : "Absent"}
      </span>
    </div>
  );
}

function ThreadingInfoPanel({ threading }: { threading: ThreadingInfo }) {
  const hasAny = threading.messageId || threading.inReplyTo || threading.references.length > 0;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <MessageSquare className="h-4 w-4" />
          Threading Info
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!hasAny ? (
          <p className="text-xs text-muted-foreground">No threading headers found.</p>
        ) : (
          <div className="space-y-2.5">
            {threading.messageId && (
              <HeaderRow label="Message-ID" value={threading.messageId} />
            )}
            {threading.inReplyTo && (
              <HeaderRow label="In-Reply-To" value={threading.inReplyTo} />
            )}
            {threading.references.length > 0 && (
              <div className="space-y-1">
                <span className="text-xs font-medium text-muted-foreground">
                  References ({threading.references.length})
                </span>
                <div className="space-y-0.5">
                  {threading.references.map((ref, i) => (
                    <p key={i} className="text-xs font-mono text-muted-foreground break-all">
                      {ref}
                    </p>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// --- Main Component ---

function EmailAnalysis({ headers }: EmailAnalysisProps) {
  const auth = useMemo(() => parseAuthenticationResults(headers), [headers]);
  const route = useMemo(() => parseReceivedHeaders(headers), [headers]);
  const security = useMemo(() => parseSecurityHeaders(headers), [headers]);
  const threading = useMemo(() => parseThreadingInfo(headers), [headers]);

  return (
    <ScrollArea className="max-h-[600px]">
      <div className="space-y-4 p-1">
        {auth && <AuthenticationResultsPanel auth={auth} />}
        <RoutingAnalysis route={route} />
        <SecurityHeadersPanel security={security} />
        <ThreadingInfoPanel threading={threading} />
      </div>
    </ScrollArea>
  );
}

export { EmailAnalysis };
