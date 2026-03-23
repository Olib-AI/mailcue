import {
  Loader2,
  AlertCircle,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Info,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useProductionStatus } from "@/hooks/use-production-status";
import type { ProductionStatus } from "@/types/api";

interface ReadinessCheck {
  name: string;
  passed: boolean;
  detail: string;
}

function buildChecks(data: ProductionStatus): ReadinessCheck[] {
  const isProduction = data.mode === "production";
  return [
    {
      name: "TLS Certificate",
      passed: data.tls_configured,
      detail: data.tls_configured
        ? "A TLS certificate is configured."
        : "No TLS certificate configured. Upload or configure a certificate for encrypted connections.",
    },
    {
      name: "Email Domains",
      passed: data.domains_configured > 0,
      detail:
        data.domains_configured > 0
          ? `${data.domains_configured} domain(s) configured, ${data.domains_verified} fully verified.`
          : "No email domains configured. Add at least one domain to send and receive email.",
    },
    {
      name: "DNS Verification",
      passed: data.domains_configured > 0 && data.domains_verified === data.domains_configured,
      detail:
        data.domains_configured === 0
          ? "No domains to verify."
          : data.domains_verified === data.domains_configured
            ? "All domains have verified DNS records."
            : `${data.domains_verified} of ${data.domains_configured} domain(s) fully verified. Check the Domains tab for details.`,
    },
    {
      name: "Postfix Strict Mode",
      passed: data.postfix_strict_mode,
      detail: data.postfix_strict_mode
        ? "Postfix is running in strict production mode."
        : "Postfix is running in relaxed mode. Set MAILCUE_MODE=production for strict security.",
    },
    {
      name: "Dovecot TLS Required",
      passed: data.dovecot_tls_required,
      detail: data.dovecot_tls_required
        ? "Dovecot requires TLS for all connections."
        : isProduction && !data.tls_configured
          ? "TLS is not configured. Dovecot cannot enforce TLS without a certificate."
          : "Dovecot does not require TLS. This is expected in test/development mode.",
    },
    {
      name: "Secure Cookies",
      passed: data.secure_cookies,
      detail: data.secure_cookies
        ? "Cookies are set with the Secure flag."
        : "Cookies are not using the Secure flag. This is expected in test/development mode.",
    },
    {
      name: "ACME / Let's Encrypt",
      passed: data.acme_configured,
      detail: data.acme_configured
        ? "ACME automatic certificate management is configured."
        : "ACME is not configured. Set ACME_EMAIL to enable automatic Let's Encrypt certificates.",
    },
  ];
}

function ProductionStatusPanel() {
  const { data, isLoading, isError, error, refetch } = useProductionStatus();

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-8">
          <AlertCircle className="h-10 w-10 text-destructive mb-3" />
          <p className="text-sm text-destructive mb-3">
            {error instanceof Error
              ? error.message
              : "Failed to load production status"}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refetch()}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  const isProduction = data.mode === "production";
  const checks = buildChecks(data);
  const allPassed = checks.every((c) => c.passed);

  return (
    <div className="space-y-4">
      {/* Overview Card */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-muted-foreground" />
              <CardTitle className="text-base">Production Readiness</CardTitle>
            </div>
            <div className="flex items-center gap-2">
              <Badge
                className={
                  isProduction
                    ? "bg-green-600 text-white"
                    : "bg-amber-500 text-white"
                }
              >
                {data.mode} mode
              </Badge>
              {allPassed ? (
                <Badge className="bg-green-600 text-white">Ready</Badge>
              ) : (
                <Badge variant="secondary">Not Ready</Badge>
              )}
            </div>
          </div>
          <CardDescription>
            {isProduction
              ? "The server is running in production mode."
              : "The server is running in test/development mode. Production security features are relaxed for easier testing."}
          </CardDescription>
        </CardHeader>
      </Card>

      {/* Test mode notice */}
      {!isProduction && (
        <Card className="border-amber-500/50 bg-amber-500/5">
          <CardContent className="flex items-start gap-3 p-4">
            <Info className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
            <div className="space-y-1">
              <p className="text-sm font-medium">Test / Development Mode</p>
              <p className="text-xs text-muted-foreground">
                In test mode, TLS requirements are relaxed, self-signed
                certificates are accepted, and security restrictions are reduced.
                Set <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">MAILCUE_MODE=production</code> to
                enable strict security checks.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Readiness Checks */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Readiness Checks</CardTitle>
          <CardDescription>
            Each check verifies a requirement for production deployment.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {checks.map((check) => (
              <div
                key={check.name}
                className="flex items-start gap-3 rounded-md border p-3"
              >
                {check.passed ? (
                  <CheckCircle2 className="h-5 w-5 text-green-500 mt-0.5 shrink-0" />
                ) : (
                  <XCircle className="h-5 w-5 text-destructive mt-0.5 shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{check.name}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {check.detail}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Refresh */}
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          onClick={() => void refetch()}
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh Status
        </Button>
      </div>
    </div>
  );
}

export { ProductionStatusPanel };
