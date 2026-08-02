import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Network,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useTunnelStatus } from "@/hooks/use-tunnels";
import type { EffectiveTunnelStatus } from "@/types/api";

function HealthBadge({ tunnel }: { tunnel: EffectiveTunnelStatus }) {
  if (!tunnel.enabled) return <Badge variant="secondary">Disabled</Badge>;
  if (tunnel.healthy === true) {
    return (
      <Badge className="bg-green-600 text-white hover:bg-green-600">
        <CheckCircle2 className="mr-1 h-3 w-3" /> Healthy
      </Badge>
    );
  }
  if (tunnel.healthy === false) {
    return (
      <Badge variant="destructive">
        <XCircle className="mr-1 h-3 w-3" /> Unhealthy
      </Badge>
    );
  }
  return <Badge variant="outline">Status unavailable</Badge>;
}

function valueOrDash(value: number | null): string {
  return value === null ? "—" : value.toLocaleString();
}

export function TunnelStatusPanel() {
  const { data, isLoading, isError, error, isFetching, refetch } = useTunnelStatus();

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center py-10">
          <AlertTriangle className="mb-3 h-9 w-9 text-destructive" />
          <p className="mb-3 text-sm text-destructive">
            {error instanceof Error ? error.message : "Could not load tunnel status"}
          </p>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" /> Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <Network className="h-5 w-5 text-muted-foreground" />
                <CardTitle className="text-base">SMTP Tunnel Sidecar</CardTitle>
                <Badge variant={data.sidecar_reachable ? "default" : "destructive"}>
                  {data.sidecar_reachable ? "Reachable" : "Unavailable"}
                </Badge>
              </div>
              <CardDescription className="mt-1">
                Effective tunnel configuration and live sidecar pool health.
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={isFetching}
              onClick={() => void refetch()}
            >
              <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </CardHeader>
        {data.status_detail && (
          <CardContent>
            <div className="flex items-start gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 p-3 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <span>{data.status_detail}</span>
            </div>
          </CardContent>
        )}
      </Card>

      {data.tunnels.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No effective tunnels were found in the database or mounted sidecar configuration.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {data.tunnels.map((tunnel) => (
            <Card key={tunnel.id}>
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="text-base">{tunnel.name}</CardTitle>
                    <CardDescription className="mt-1 font-mono">
                      {tunnel.endpoint_host}:{tunnel.endpoint_port}
                    </CardDescription>
                  </div>
                  <HealthBadge tunnel={tunnel} />
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">Priority {tunnel.weight}</Badge>
                  <Badge variant={tunnel.managed ? "default" : "secondary"}>
                    {tunnel.managed ? "MailCue managed" : "File managed · read only"}
                  </Badge>
                </div>
                <dl className="grid grid-cols-2 gap-x-5 gap-y-2 text-sm sm:grid-cols-3">
                  <div>
                    <dt className="text-muted-foreground">Idle connections</dt>
                    <dd className="font-medium">{valueOrDash(tunnel.idle_connections)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">In flight</dt>
                    <dd className="font-medium">{valueOrDash(tunnel.inflight)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Successful</dt>
                    <dd className="font-medium">{valueOrDash(tunnel.requests_ok)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Failed</dt>
                    <dd className="font-medium">{valueOrDash(tunnel.requests_err)}</dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-muted-foreground">Last success</dt>
                    <dd className="font-medium">
                      {tunnel.last_success
                        ? new Date(tunnel.last_success).toLocaleString()
                        : "No successful operation recorded"}
                    </dd>
                  </div>
                </dl>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
