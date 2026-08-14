import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Info,
  Loader2,
  RefreshCw,
  Sparkles,
  Target,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { formatFullDate } from "@/lib/utils";
import { api } from "@/lib/api";
import {
  useDeliverabilityCapabilities,
  useDeliverabilityRuns,
  useRunDeliverabilityChecks,
} from "@/hooks/use-emails";
import type {
  DeliverabilityCategory,
  DeliverabilityCheck,
  DeliverabilityReport,
  EmailDetail,
} from "@/types/api";
import { EmailHeaders } from "./email-headers";
import { EmailRenderer } from "./email-renderer";

interface DeliverabilityDetailProps {
  email: EmailDetail;
  report: DeliverabilityReport | undefined;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}

const statusStyles = {
  pass: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300",
  warning: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300",
  fail: "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300",
  info: "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-300",
} as const;

function scoreColor(score: number): string {
  if (score >= 90) return "#10b981";
  if (score >= 75) return "#22c55e";
  if (score >= 50) return "#f59e0b";
  return "#ef4444";
}

function ScoreGauge({ report }: { report: DeliverabilityReport }) {
  const color = scoreColor(report.score);
  return (
    <div className="flex flex-col items-center text-center">
      <div
        className="relative grid h-44 w-44 place-items-center rounded-full"
        style={{
          background: `conic-gradient(${color} ${report.score * 3.6}deg, var(--color-muted) 0deg)`,
        }}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={report.score}
        aria-label={`Deliverability score ${report.score} out of 100`}
      >
        <div className="grid h-36 w-36 place-items-center rounded-full bg-card shadow-inner">
          <div>
            <div className="text-5xl font-bold tracking-tight" style={{ color }}>
              {report.score}
            </div>
            <div className="text-xs font-medium uppercase tracking-[0.2em] text-muted-foreground">
              out of 100
            </div>
          </div>
        </div>
      </div>
      <Badge className="mt-4 capitalize" style={{ backgroundColor: color }}>
        {report.verdict.replace("_", " ")}
      </Badge>
      <p className="mt-3 max-w-sm text-sm text-muted-foreground">{report.summary}</p>
    </div>
  );
}

function StatusIcon({ check }: { check: DeliverabilityCheck }) {
  const className = "h-4 w-4 shrink-0";
  if (check.status === "pass") return <CheckCircle2 className={className} />;
  if (check.status === "fail") return <AlertCircle className={className} />;
  if (check.status === "warning") return <CircleAlert className={className} />;
  return <Info className={className} />;
}

function ArtifactPreview({ path, title }: { path: string; title: string }) {
  const [source, setSource] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    void api
      .blob(path)
      .then((blob) => {
        if (!active) return;
        if (!blob.type.startsWith("image/")) {
          throw new Error("Artifact is not an image");
        }
        objectUrl = URL.createObjectURL(blob);
        setSource(objectUrl);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);

  if (failed) {
    return <p className="mt-2 rounded-md border p-3 text-muted-foreground">Artifact could not be loaded.</p>;
  }
  if (!source) {
    return <div className="mt-2 grid h-32 place-items-center rounded-md border"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>;
  }
  return (
    <a href={source} target="_blank" rel="noreferrer" className="mt-2 block overflow-hidden rounded-md border bg-white">
      <img src={source} alt={title} loading="lazy" className="max-h-80 w-full object-contain" />
    </a>
  );
}

function CheckRow({ check }: { check: DeliverabilityCheck }) {
  return (
    <div className="rounded-lg border bg-background/70 p-3">
      <div className="flex items-start gap-3">
        <div className={cn("mt-0.5 rounded-full border p-1.5", statusStyles[check.status])}>
          <StatusIcon check={check} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-sm font-semibold">{check.title}</h4>
            {check.max_points > 0 && (
              <span className="text-xs tabular-nums text-muted-foreground">
                {Number(check.points.toFixed(1))}/{Number(check.max_points.toFixed(1))} points
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{check.summary}</p>
          {check.details.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
              {check.details.map((detail) => (
                <li key={detail} className="break-words font-mono">{detail}</li>
              ))}
            </ul>
          )}
          {check.evidence.length > 0 && (
            <details className="mt-2 rounded-md border bg-muted/20 px-3 py-2 text-xs">
              <summary className="cursor-pointer font-medium">
                {check.evidence.length} evidence item{check.evidence.length === 1 ? "" : "s"}
              </summary>
              <div className="mt-2 space-y-2">
                {check.evidence.map((item, index) => (
                  <div key={`${item.code}-${index}-${String(item.value)}`} className="border-t pt-2 first:border-0 first:pt-0">
                    <div className="flex flex-wrap justify-between gap-2 font-mono">
                      <span>{item.title}</span><span>{item.score ?? item.value ?? "observed"}</span>
                    </div>
                    {typeof item.value === "string" && item.value.startsWith("/api/v1/deliverability/artifacts/") && (
                      <ArtifactPreview path={item.value} title={item.title} />
                    )}
                    {item.description && <p className="mt-1 text-muted-foreground">{item.description}</p>}
                    {item.recommendation && <p className="mt-1">{item.recommendation}</p>}
                  </div>
                ))}
              </div>
            </details>
          )}
          {check.recommendation && (
            <div className="mt-2 rounded-md bg-primary/5 px-3 py-2 text-xs text-foreground">
              <span className="font-semibold">How to improve: </span>
              {check.recommendation}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CategorySection({ category }: { category: DeliverabilityCategory }) {
  const failures = category.checks.filter((check) => check.status === "fail").length;
  const warnings = category.checks.filter((check) => check.status === "warning").length;
  return (
    <details className="group overflow-hidden rounded-xl border bg-card">
      <summary className="flex cursor-pointer list-none items-center gap-3 p-4 hover:bg-muted/40">
        <div className="grid h-11 w-11 place-items-center rounded-full bg-muted text-sm font-bold tabular-nums">
          {category.score ?? "N/A"}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold">{category.title}</h3>
          <p className="text-xs text-muted-foreground">
            {failures > 0
              ? `${failures} failed check${failures === 1 ? "" : "s"}`
              : warnings > 0
                ? `${warnings} warning${warnings === 1 ? "" : "s"}`
                : "All scored checks passed"}
          </p>
        </div>
        <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="space-y-2 border-t bg-muted/20 p-3">
        {category.checks.map((check) => <CheckRow key={check.id} check={check} />)}
      </div>
    </details>
  );
}

function DeliverabilityDetail({
  email,
  report,
  isLoading,
  isError,
  onRetry,
}: DeliverabilityDetailProps) {
  const extended = useRunDeliverabilityChecks();
  const capabilities = useDeliverabilityCapabilities();
  const storedRuns = useDeliverabilityRuns(report?.report_id);
  const storedRun = storedRuns.data?.find((run) => run.categories.length > 0);
  const extendedCategories = extended.data?.categories ?? storedRun?.categories ?? [];
  const visualProviderChecks = useMemo(() => {
    const available = new Set(
      capabilities.data?.capabilities
        .filter((capability) => capability.status === "available")
        .map((capability) => capability.id) ?? []
    );
    const candidates: Array<[
      "visual" | "placement" | "client_previews" | "ai_analysis",
      string,
    ]> = [
      ["visual", "visual_rendering"],
      ["placement", "inbox_placement"],
      ["client_previews", "client_previews"],
      ["ai_analysis", "ai_analysis"],
    ];
    return candidates
      .filter(([, capability]) => available.has(capability))
      .map(([check]) => check);
  }, [capabilities.data]);
  return (
    <div className="h-full overflow-auto bg-gradient-to-b from-violet-50/60 via-background to-background dark:from-violet-950/10">
      <div className="mx-auto max-w-6xl space-y-5 p-4 md:p-7">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-medium text-violet-600 dark:text-violet-300">
              <Sparkles className="h-4 w-4" /> Deliverability report
            </div>
            <h1 className="text-2xl font-bold tracking-tight">{email.subject || "(no subject)"}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              From {email.from_address || "unknown sender"} · {formatFullDate(email.date)}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={extended.isPending}
              onClick={() => extended.mutate({
                mailbox: email.mailbox,
                uid: email.uid,
                checks: ["dns", "reputation", "links"],
              })}
            >
              {extended.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              Extended checks
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={extended.isPending || capabilities.isLoading || visualProviderChecks.length === 0}
              onClick={() => extended.mutate({
                mailbox: email.mailbox,
                uid: email.uid,
                checks: visualProviderChecks,
              })}
              title={visualProviderChecks.length > 0 ? "Runs local visuals and available configured providers. Providers may receive the original message." : "No visual or provider checks are available."}
            >
              {extended.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}
              Visual and provider checks
            </Button>
            <Badge variant="outline" className="font-mono">UID {email.uid}</Badge>
          </div>
        </div>

        {isLoading && (
          <Card><CardContent className="flex items-center justify-center gap-2 py-16 text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin" />Analyzing the original message</CardContent></Card>
        )}
        {isError && (
          <Card><CardContent className="flex flex-col items-center gap-3 py-12 text-center"><AlertCircle className="h-8 w-8 text-destructive" /><p className="text-sm">The deliverability report could not be generated.</p><Button variant="outline" size="sm" onClick={onRetry}><RefreshCw className="mr-2 h-4 w-4" />Retry</Button></CardContent></Card>
        )}
        {report && (
          <>
            <div className="grid gap-5 lg:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.2fr)]">
              <Card className="border-violet-200/60 shadow-lg shadow-violet-500/5 dark:border-violet-900/50">
                <CardContent className="grid min-h-[360px] place-items-center p-7"><ScoreGauge report={report} /></CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="flex items-center gap-2"><Target className="h-5 w-5 text-violet-500" />Priority fixes</CardTitle></CardHeader>
                <CardContent>
                  {report.top_recommendations.length > 0 ? (
                    <ol className="space-y-3">
                      {report.top_recommendations.map((item, index) => (
                        <li key={item} className="flex gap-3 rounded-lg border bg-muted/20 p-3 text-sm">
                          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-violet-100 text-xs font-bold text-violet-700 dark:bg-violet-950 dark:text-violet-300">{index + 1}</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <div className="flex min-h-48 flex-col items-center justify-center text-center"><CheckCircle2 className="mb-3 h-10 w-10 text-emerald-500" /><p className="font-medium">No priority fixes found</p><p className="mt-1 text-sm text-muted-foreground">Review the detailed checks for informational notes.</p></div>
                  )}
                </CardContent>
              </Card>
            </div>

            <div className="space-y-3">
              {report.categories.map((category) => <CategorySection key={category.id} category={category} />)}
              {extendedCategories.map((category) => <CategorySection key={`extended-${category.id}`} category={category} />)}
            </div>

            {extended.data?.error_detail && (
              <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                {extended.data.error_detail}
              </p>
            )}

            <Card>
              <CardHeader><CardTitle className="text-base">Message preview and evidence</CardTitle></CardHeader>
              <CardContent>
                <Tabs defaultValue={email.html_body ? "preview" : "text"}>
                  <TabsList>
                    {email.html_body && <TabsTrigger value="preview">Preview</TabsTrigger>}
                    {email.text_body && <TabsTrigger value="text">Plain text</TabsTrigger>}
                    <TabsTrigger value="headers">Headers</TabsTrigger>
                  </TabsList>
                  {email.html_body && <TabsContent value="preview"><EmailRenderer html={email.html_body} mailbox={email.mailbox} uid={email.uid} attachments={email.attachments} /></TabsContent>}
                  {email.text_body && <TabsContent value="text"><pre className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-lg bg-muted/50 p-4 font-mono text-sm">{email.text_body}</pre></TabsContent>}
                  <TabsContent value="headers"><EmailHeaders headers={email.raw_headers} /></TabsContent>
                </Tabs>
              </CardContent>
            </Card>

            <div className="rounded-lg border bg-muted/20 p-4 text-xs text-muted-foreground">
              <p className="font-semibold text-foreground">What this score does not claim</p>
              <ul className="mt-2 list-disc space-y-1 pl-4">{report.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
              <Separator className="my-3" />
              <p>Scoring model {report.score_version}. Generated from the received message and local mail-server evidence.</p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export { DeliverabilityDetail };
