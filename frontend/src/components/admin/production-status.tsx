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
                  data.is_production
                    ? "bg-green-600 text-white"
                    : "bg-amber-500 text-white"
                }
              >
                {data.mode} mode
              </Badge>
              {data.ready ? (
                <Badge className="bg-green-600 text-white">Ready</Badge>
              ) : (
                <Badge variant="secondary">Not Ready</Badge>
              )}
            </div>
          </div>
          <CardDescription>
            {data.is_production
              ? "The server is running in production mode."
              : "The server is running in test/development mode. Production security features are relaxed for easier testing."}
          </CardDescription>
        </CardHeader>
      </Card>

      {/* Test mode notice */}
      {!data.is_production && (
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
            {data.checks.map((check) => (
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
