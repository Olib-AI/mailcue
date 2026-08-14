import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { AlertCircle, Bell, CheckCircle2, Gauge, History, Settings2, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useMailboxes } from "@/hooks/use-mailboxes";
import { useAuth } from "@/hooks/use-auth";
import { useWarmupAccounts } from "@/hooks/use-warmup";
import { useUIStore } from "@/stores/ui-store";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

interface ReportSummary {
  id: string; uid: string; folder: string; message_id: string; score: number; verdict: string;
  is_baseline: boolean; created_at: string;
}
interface ReportHistory { reports: ReportSummary[]; total: number; }
interface TrendPoint { report_id: string; score: number; verdict: string; created_at: string; }
interface Trend { points: TrendPoint[]; average_score: number | null; minimum_score: number | null; maximum_score: number | null; score_delta: number | null; }
interface Capability { id: string; title: string; description: string; status: string; reason: string | null; }
interface AlertItem { id: string; title: string; detail: string; severity: string; acknowledged: boolean; created_at: string; }
interface AlertList { alerts: AlertItem[]; total: number; }
interface PolicyItem { id: string; name: string; enabled: boolean; minimum_score: number; maximum_regression: number; fail_on_statuses: string[]; required_check_ids: string[]; required_capabilities: string[]; }
interface ScheduleItem { id: string; name: string; enabled: boolean; interval_minutes: number; checks: string[]; policy_id: string | null; next_run_at: string | null; }
interface ProviderItem { id: string; name: string; kind: "preview" | "placement" | "analysis"; adapter: string; enabled: boolean; config: Record<string, string | number | boolean | string[]>; has_secret: boolean; last_status: string; last_error: string | null; }
interface Comparison {
  before_report_id: string; after_report_id: string; before_score: number; after_score: number;
  score_delta: number; improved: number; regressed: number; unchanged: number;
  categories: Array<{ id: string; title: string; before_score: number | null; after_score: number | null; score_delta: number | null }>;
}
type RunCheck = "dns" | "reputation" | "links" | "visual" | "placement" | "client_previews" | "ai_analysis";

function scoreTone(score: number) {
  return score >= 90 ? "text-emerald-600" : score >= 75 ? "text-lime-600" : score >= 50 ? "text-amber-600" : "text-red-600";
}

export function DeliverabilityPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isAdmin = useAuth((state) => state.user?.is_admin ?? false);
  const warmupAccounts = useWarmupAccounts(isAdmin);
  const { data: mailboxData } = useMailboxes();
  const selectedMailbox = useUIStore((state) => state.selectedMailbox);
  const setSelectedMailbox = useUIStore((state) => state.setSelectedMailbox);
  const setSelectedFolder = useUIStore((state) => state.setSelectedFolder);
  const setSelectedEmailUid = useUIStore((state) => state.setSelectedEmailUid);
  const mailboxes = useMemo(
    () => (mailboxData?.mailboxes ?? []).filter((mailbox) => mailbox.purpose === "deliverability"),
    [mailboxData]
  );
  const mailbox = mailboxes.some((item) => item.address === selectedMailbox)
    ? selectedMailbox
    : mailboxes[0]?.address ?? null;
  const [policyName, setPolicyName] = useState("Release gate");
  const [minimumScore, setMinimumScore] = useState(80);
  const [scheduleName, setScheduleName] = useState("Hourly latest message");
  const [scheduleMinutes, setScheduleMinutes] = useState(60);
  const [scheduleChecks, setScheduleChecks] = useState<RunCheck[]>(["dns", "reputation", "links"]);
  const [schedulePolicyId, setSchedulePolicyId] = useState("");
  const [providerName, setProviderName] = useState("Client previews");
  const [providerKind, setProviderKind] = useState<"preview" | "placement" | "analysis">("preview");
  const [providerEndpoint, setProviderEndpoint] = useState("");
  const [providerSecret, setProviderSecret] = useState("");
  const [seedAccountIds, setSeedAccountIds] = useState<string[]>([]);

  useEffect(() => {
    if (mailbox && mailbox !== selectedMailbox) setSelectedMailbox(mailbox);
  }, [mailbox, selectedMailbox, setSelectedMailbox]);

  const encoded = encodeURIComponent(mailbox ?? "");
  const history = useQuery({
    queryKey: ["deliverability", "history", mailbox],
    queryFn: () => api.get<ReportHistory>(`/deliverability/reports?mailbox=${encoded}&page_size=50`),
    enabled: !!mailbox,
  });
  const trend = useQuery({
    queryKey: ["deliverability", "trend", mailbox],
    queryFn: () => api.get<Trend>(`/deliverability/trends?mailbox=${encoded}&limit=100`),
    enabled: !!mailbox,
  });
  const latestReportId = history.data?.reports[0]?.id;
  const comparison = useQuery({
    queryKey: ["deliverability", "comparison", latestReportId],
    queryFn: () => api.get<Comparison>(`/deliverability/reports/${latestReportId}/comparison`),
    enabled: !!latestReportId && (history.data?.reports.length ?? 0) > 1,
    retry: false,
  });
  const capabilities = useQuery({
    queryKey: ["deliverability", "capabilities"],
    queryFn: () => api.get<{ capabilities: Capability[] }>("/deliverability/capabilities"),
  });
  const alerts = useQuery({
    queryKey: ["deliverability", "alerts"],
    queryFn: () => api.get<AlertList>("/deliverability/alerts?acknowledged=false"),
  });
  const policies = useQuery({
    queryKey: ["deliverability", "policies", mailbox],
    queryFn: () => api.get<PolicyItem[]>(`/deliverability/policies?mailbox=${encoded}`),
    enabled: !!mailbox,
  });
  const schedules = useQuery({
    queryKey: ["deliverability", "schedules", mailbox],
    queryFn: () => api.get<ScheduleItem[]>(`/deliverability/schedules?mailbox=${encoded}`),
    enabled: !!mailbox,
  });
  const providers = useQuery({
    queryKey: ["deliverability", "providers"],
    queryFn: () => api.get<ProviderItem[]>("/deliverability/providers"),
  });
  const acknowledge = useMutation({
    mutationFn: (id: string) => api.post(`/deliverability/alerts/${id}/acknowledge`, {}),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["deliverability", "alerts"] }),
  });
  const setBaseline = useMutation({
    mutationFn: (reportId: string) => api.put(`/deliverability/reports/${reportId}/baseline`, { is_baseline: true }),
    onSuccess: () => { toast.success("Baseline selected"); void queryClient.invalidateQueries({ queryKey: ["deliverability", "history", mailbox] }); void queryClient.invalidateQueries({ queryKey: ["deliverability", "comparison"] }); },
  });
  const createPolicy = useMutation({
    mutationFn: () => api.post("/deliverability/policies", {
      name: policyName, mailbox, minimum_score: minimumScore, maximum_regression: 5,
      fail_on_statuses: ["fail"], required_check_ids: ["spf", "dkim", "dmarc"],
      required_capabilities: ["local_analysis"],
    }),
    onSuccess: () => { toast.success("Policy created"); void queryClient.invalidateQueries({ queryKey: ["deliverability", "policies", mailbox] }); },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Could not create policy"),
  });
  const createSchedule = useMutation({
    mutationFn: () => api.post("/deliverability/schedules", {
      name: scheduleName, mailbox, enabled: true, interval_minutes: scheduleMinutes,
      checks: scheduleChecks, policy_id: schedulePolicyId || null,
    }),
    onSuccess: () => { toast.success("Schedule created"); void queryClient.invalidateQueries({ queryKey: ["deliverability", "schedules", mailbox] }); },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Could not create schedule"),
  });
  const createProvider = useMutation({
    mutationFn: () => api.post("/deliverability/providers", providerKind !== "placement" ? {
      name: providerName, kind: providerKind, adapter: providerKind === "preview" ? "generic_http_preview" : "generic_http_analysis", enabled: true,
      config: { base_url: providerEndpoint }, secret: providerSecret || null,
    } : {
      name: providerName, kind: "placement", adapter: "seed_imap", enabled: true,
      config: { account_ids: seedAccountIds, folders: ["INBOX", "Spam", "Junk", "Promotions"] },
    }),
    onSuccess: () => { toast.success("Provider created"); setProviderSecret(""); void queryClient.invalidateQueries({ queryKey: ["deliverability", "providers"] }); void queryClient.invalidateQueries({ queryKey: ["deliverability", "capabilities"] }); },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Could not create provider"),
  });
  const removeAutomation = useMutation({
    mutationFn: ({ kind, id }: { kind: "policies" | "schedules" | "providers"; id: string }) =>
      api.delete(`/deliverability/${kind}/${id}`),
    onSuccess: (_result, variables) => {
      toast.success("Configuration removed");
      void queryClient.invalidateQueries({ queryKey: ["deliverability", variables.kind] });
      if (variables.kind === "providers") void queryClient.invalidateQueries({ queryKey: ["deliverability", "capabilities"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Could not remove configuration"),
  });
  const toggleSchedule = useMutation({
    mutationFn: (item: ScheduleItem) => api.put(`/deliverability/schedules/${item.id}`, {
      name: item.name, mailbox, enabled: !item.enabled, interval_minutes: item.interval_minutes,
      checks: item.checks, policy_id: item.policy_id,
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["deliverability", "schedules", mailbox] }),
  });
  const togglePolicy = useMutation({
    mutationFn: (item: PolicyItem) => api.put(`/deliverability/policies/${item.id}`, {
      name: item.name, mailbox, enabled: !item.enabled, minimum_score: item.minimum_score,
      maximum_regression: item.maximum_regression, fail_on_statuses: item.fail_on_statuses,
      required_check_ids: item.required_check_ids, required_capabilities: item.required_capabilities,
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["deliverability", "policies", mailbox] }),
  });
  const toggleProvider = useMutation({
    mutationFn: (item: ProviderItem) => api.put(`/deliverability/providers/${item.id}`, {
      name: item.name, kind: item.kind, adapter: item.adapter, enabled: !item.enabled,
      config: item.config, secret: null,
    }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["deliverability", "providers"] }); void queryClient.invalidateQueries({ queryKey: ["deliverability", "capabilities"] }); },
  });

  const openReport = (report: ReportSummary) => {
    if (!mailbox) return;
    setSelectedMailbox(mailbox);
    setSelectedFolder(report.folder);
    setSelectedEmailUid(report.uid);
    void navigate("/mail");
  };

  if (!mailbox) {
    return <div className="grid h-full place-items-center p-8 text-center"><div><Gauge className="mx-auto mb-3 h-10 w-10 text-violet-500" /><h1 className="text-xl font-semibold">No deliverability mailbox yet</h1><p className="mt-2 text-sm text-muted-foreground">Create one from Mailboxes and select Deliverability testing as its purpose.</p></div></div>;
  }

  const latest = history.data?.reports[0];
  return (
    <div className="h-full overflow-auto bg-gradient-to-b from-violet-50/60 via-background to-background p-4 dark:from-violet-950/10 md:p-7">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div><p className="text-sm font-medium text-violet-600">Deliverability intelligence</p><h1 className="text-3xl font-bold tracking-tight">Testing command center</h1><p className="mt-1 text-sm text-muted-foreground">Scores, regressions, capabilities, automation, and placement evidence.</p></div>
          <Select className="w-[280px]" value={mailbox} onChange={(event) => setSelectedMailbox(event.target.value)}>{mailboxes.map((item) => <option key={item.address} value={item.address}>{item.address}</option>)}</Select>
        </header>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Card><CardContent className="pt-6"><p className="text-xs uppercase tracking-wider text-muted-foreground">Latest score</p><p className={`mt-2 text-4xl font-bold ${latest ? scoreTone(latest.score) : ""}`}>{latest?.score ?? "N/A"}</p><p className="mt-1 text-sm capitalize text-muted-foreground">{latest?.verdict.replace("_", " ") ?? "Run a test email"}</p></CardContent></Card>
          <Card><CardContent className="pt-6"><p className="text-xs uppercase tracking-wider text-muted-foreground">Average</p><p className="mt-2 text-4xl font-bold">{trend.data?.average_score ?? "N/A"}</p><p className="mt-1 text-sm text-muted-foreground">Across {trend.data?.points.length ?? 0} reports</p></CardContent></Card>
          <Card><CardContent className="pt-6"><p className="text-xs uppercase tracking-wider text-muted-foreground">Change</p><p className={`mt-2 text-4xl font-bold ${(trend.data?.score_delta ?? 0) >= 0 ? "text-emerald-600" : "text-red-600"}`}>{trend.data?.score_delta == null ? "N/A" : `${trend.data.score_delta > 0 ? "+" : ""}${trend.data.score_delta}`}</p><p className="mt-1 text-sm text-muted-foreground">Oldest to newest loaded report</p></CardContent></Card>
          <Card><CardContent className="pt-6"><p className="text-xs uppercase tracking-wider text-muted-foreground">Open alerts</p><p className="mt-2 text-4xl font-bold text-amber-600">{alerts.data?.total ?? 0}</p><p className="mt-1 text-sm text-muted-foreground">Policy and automation findings</p></CardContent></Card>
        </div>

        <Card><CardHeader><CardTitle className="flex items-center gap-2"><Gauge className="h-5 w-5 text-violet-500" />Score trend</CardTitle></CardHeader><CardContent><div className="flex h-44 items-end gap-1 rounded-lg border bg-muted/20 p-3">{(trend.data?.points ?? []).map((point) => <button key={point.report_id} type="button" onClick={() => { const report = history.data?.reports.find((item) => item.id === point.report_id); if (report) openReport(report); }} className="group relative min-w-1 flex-1 rounded-t bg-violet-500/75 hover:bg-violet-500" style={{ height: `${Math.max(point.score, 4)}%` }} title={`${point.score}/100 on ${new Date(point.created_at).toLocaleString()}`}><span className="sr-only">Score {point.score}</span></button>)}</div></CardContent></Card>

        {comparison.data && <Card><CardHeader><CardTitle>Latest regression comparison</CardTitle></CardHeader><CardContent><div className="grid gap-3 sm:grid-cols-4"><div className="rounded-lg bg-muted p-3"><p className={`text-2xl font-bold ${comparison.data.score_delta >= 0 ? "text-emerald-600" : "text-red-600"}`}>{comparison.data.score_delta > 0 ? "+" : ""}{comparison.data.score_delta}</p><p className="text-xs text-muted-foreground">Score change</p></div><div className="rounded-lg bg-emerald-50 p-3 dark:bg-emerald-950/20"><p className="text-2xl font-bold text-emerald-600">{comparison.data.improved}</p><p className="text-xs text-muted-foreground">Improved checks</p></div><div className="rounded-lg bg-red-50 p-3 dark:bg-red-950/20"><p className="text-2xl font-bold text-red-600">{comparison.data.regressed}</p><p className="text-xs text-muted-foreground">Regressed checks</p></div><div className="rounded-lg bg-muted p-3"><p className="text-2xl font-bold">{comparison.data.unchanged}</p><p className="text-xs text-muted-foreground">Unchanged checks</p></div></div><div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">{comparison.data.categories.map((category) => <div key={category.id} className="flex items-center justify-between rounded-lg border p-3"><div><p className="text-sm font-medium">{category.title}</p><p className="text-xs text-muted-foreground">{category.before_score ?? "N/A"} to {category.after_score ?? "N/A"}</p></div><Badge variant={(category.score_delta ?? 0) < 0 ? "destructive" : "secondary"}>{category.score_delta == null ? "N/A" : `${category.score_delta > 0 ? "+" : ""}${category.score_delta}`}</Badge></div>)}</div></CardContent></Card>}

        <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
          <Card className="min-w-0 overflow-hidden">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <History className="h-5 w-5" />
                Report history
              </CardTitle>
            </CardHeader>
            <CardContent className="min-w-0 space-y-2">
              {(history.data?.reports ?? []).map((report) => {
                const messageLabel = report.message_id || `Message UID ${report.uid}`;
                return (
                  <div
                    key={report.id}
                    className="flex min-w-0 items-center gap-2 overflow-hidden rounded-lg border p-2"
                  >
                    <button
                      type="button"
                      onClick={() => openReport(report)}
                      className="flex min-w-0 flex-1 items-center gap-3 overflow-hidden rounded-md p-1 text-left hover:bg-muted/40"
                    >
                      <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-full bg-muted font-bold ${scoreTone(report.score)}`}>
                        {report.score}
                      </div>
                      <div className="min-w-0 flex-1 overflow-hidden">
                        <p className="truncate font-medium" title={messageLabel}>
                          {messageLabel}
                        </p>
                        <p className="truncate text-xs text-muted-foreground">
                          {new Date(report.created_at).toLocaleString()}
                        </p>
                      </div>
                      {report.is_baseline && <Badge className="shrink-0" variant="outline">Baseline</Badge>}
                      <Badge className="shrink-0 capitalize" variant="secondary">
                        {report.verdict.replace("_", " ")}
                      </Badge>
                    </button>
                    {!report.is_baseline && (
                      <Button
                        className="shrink-0"
                        size="sm"
                        variant="ghost"
                        onClick={() => setBaseline.mutate(report.id)}
                      >
                        Set baseline
                      </Button>
                    )}
                  </div>
                );
              })}
              {history.data?.reports.length === 0 && (
                <p className="py-8 text-center text-sm text-muted-foreground">
                  No scored messages yet.
                </p>
              )}
            </CardContent>
          </Card>
          <div className="space-y-6">
            <Card><CardHeader><CardTitle className="flex items-center gap-2"><Bell className="h-5 w-5" />Open alerts</CardTitle></CardHeader><CardContent className="space-y-3">{(alerts.data?.alerts ?? []).map((alert) => <div key={alert.id} className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 dark:border-amber-900 dark:bg-amber-950/20"><div className="flex gap-2"><AlertCircle className="mt-0.5 h-4 w-4 text-amber-600" /><div className="min-w-0 flex-1"><p className="text-sm font-semibold">{alert.title}</p><p className="mt-1 text-xs text-muted-foreground">{alert.detail}</p><Button className="mt-2" size="sm" variant="outline" onClick={() => acknowledge.mutate(alert.id)}>Acknowledge</Button></div></div></div>)}{alerts.data?.alerts.length === 0 && <div className="py-6 text-center"><CheckCircle2 className="mx-auto h-8 w-8 text-emerald-500" /><p className="mt-2 text-sm">No open alerts</p></div>}</CardContent></Card>
            <Card><CardHeader><CardTitle className="flex items-center gap-2"><Settings2 className="h-5 w-5" />Automation</CardTitle></CardHeader><CardContent className="space-y-4"><div className="grid grid-cols-3 gap-2 text-center"><div className="rounded-lg bg-muted p-3"><p className="text-2xl font-bold">{policies.data?.length ?? 0}</p><p className="text-xs text-muted-foreground">Policies</p></div><div className="rounded-lg bg-muted p-3"><p className="text-2xl font-bold">{schedules.data?.length ?? 0}</p><p className="text-xs text-muted-foreground">Schedules</p></div><div className="rounded-lg bg-muted p-3"><p className="text-2xl font-bold">{providers.data?.length ?? 0}</p><p className="text-xs text-muted-foreground">Providers</p></div></div>
              {((policies.data?.length ?? 0) > 0 || (schedules.data?.length ?? 0) > 0 || (providers.data?.length ?? 0) > 0) && <div className="space-y-2">
                {(policies.data ?? []).map((item) => <div key={item.id} className="flex items-center gap-2 rounded-lg border p-2"><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{item.name}</p><p className="text-xs text-muted-foreground">Policy, score {item.minimum_score}+</p></div><Button size="sm" variant="outline" onClick={() => togglePolicy.mutate(item)}>{item.enabled ? "Disable" : "Enable"}</Button><Button size="icon" variant="ghost" aria-label={`Delete policy ${item.name}`} onClick={() => removeAutomation.mutate({ kind: "policies", id: item.id })}><Trash2 className="h-4 w-4" /></Button></div>)}
                {(schedules.data ?? []).map((item) => <div key={item.id} className="flex items-center gap-2 rounded-lg border p-2"><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{item.name}</p><p className="text-xs text-muted-foreground">Every {item.interval_minutes} minutes, {item.checks.length} extended checks</p></div><Button size="sm" variant="outline" onClick={() => toggleSchedule.mutate(item)}>{item.enabled ? "Disable" : "Enable"}</Button><Button size="icon" variant="ghost" aria-label={`Delete schedule ${item.name}`} onClick={() => removeAutomation.mutate({ kind: "schedules", id: item.id })}><Trash2 className="h-4 w-4" /></Button></div>)}
                {(providers.data ?? []).map((item) => <div key={item.id} className="flex items-center gap-2 rounded-lg border p-2"><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><p className="truncate text-sm font-medium">{item.name}</p><Badge variant="outline">{item.last_status}</Badge></div><p className="text-xs text-muted-foreground">{item.kind === "preview" ? "Client preview adapter" : item.kind === "analysis" ? "AI-assisted copy review" : "Seed inbox placement"}{item.last_error ? `: ${item.last_error}` : ""}</p></div><Button size="sm" variant="outline" onClick={() => toggleProvider.mutate(item)}>{item.enabled ? "Disable" : "Enable"}</Button><Button size="icon" variant="ghost" aria-label={`Delete provider ${item.name}`} onClick={() => removeAutomation.mutate({ kind: "providers", id: item.id })}><Trash2 className="h-4 w-4" /></Button></div>)}
              </div>}
              <details className="rounded-lg border p-3"><summary className="cursor-pointer text-sm font-semibold">Create CI policy</summary><form className="mt-3 grid gap-3" onSubmit={(event) => { event.preventDefault(); createPolicy.mutate(); }}><div><Label htmlFor="policy-name">Name</Label><Input id="policy-name" value={policyName} onChange={(event) => setPolicyName(event.target.value)} /></div><div><Label htmlFor="minimum-score">Minimum score</Label><Input id="minimum-score" type="number" min={0} max={100} value={minimumScore} onChange={(event) => setMinimumScore(Number(event.target.value))} /></div><Button size="sm" disabled={createPolicy.isPending}>Create policy</Button></form></details>
              <details className="rounded-lg border p-3"><summary className="cursor-pointer text-sm font-semibold">Create recurring schedule</summary><form className="mt-3 grid gap-3" onSubmit={(event) => { event.preventDefault(); createSchedule.mutate(); }}><div><Label htmlFor="schedule-name">Name</Label><Input id="schedule-name" value={scheduleName} onChange={(event) => setScheduleName(event.target.value)} /></div><div><Label htmlFor="schedule-interval">Interval in minutes</Label><Input id="schedule-interval" type="number" min={5} max={43200} value={scheduleMinutes} onChange={(event) => setScheduleMinutes(Number(event.target.value))} /></div><fieldset className="grid grid-cols-2 gap-2"><legend className="mb-1 text-sm font-medium">Extended checks</legend>{(["dns", "reputation", "links", "visual", "placement", "client_previews", "ai_analysis"] as RunCheck[]).map((check) => <label key={check} className="flex items-center gap-2 rounded-md border p-2 text-xs"><input type="checkbox" checked={scheduleChecks.includes(check)} onChange={(event) => setScheduleChecks((current) => event.target.checked ? [...current, check] : current.filter((item) => item !== check))} /><span>{check.replaceAll("_", " ")}</span></label>)}</fieldset><div><Label htmlFor="schedule-policy">Policy after scoring</Label><Select id="schedule-policy" value={schedulePolicyId} onChange={(event) => setSchedulePolicyId(event.target.value)}><option value="">No policy</option>{(policies.data ?? []).filter((policy) => policy.enabled).map((policy) => <option key={policy.id} value={policy.id}>{policy.name}</option>)}</Select></div>{scheduleChecks.some((check) => ["placement", "client_previews", "ai_analysis"].includes(check)) && <p className="rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-200">Scheduled provider checks may transmit the original message to providers you configured.</p>}<Button size="sm" disabled={createSchedule.isPending}>Create schedule</Button></form></details>
              <details className="rounded-lg border p-3"><summary className="cursor-pointer text-sm font-semibold">Add optional provider</summary><form className="mt-3 grid gap-3" onSubmit={(event) => { event.preventDefault(); createProvider.mutate(); }}><div><Label htmlFor="provider-name">Name</Label><Input id="provider-name" value={providerName} onChange={(event) => setProviderName(event.target.value)} /></div><div><Label htmlFor="provider-kind">Provider type</Label><Select id="provider-kind" value={providerKind} onChange={(event) => setProviderKind(event.target.value as "preview" | "placement" | "analysis")}><option value="preview">Real-client preview HTTPS adapter</option><option value="analysis">AI-assisted copy review HTTPS adapter</option>{isAdmin && <option value="placement">BYO seed inboxes</option>}</Select></div>{providerKind !== "placement" ? <div><Label htmlFor="provider-endpoint">HTTPS endpoint</Label><Input id="provider-endpoint" value={providerEndpoint} onChange={(event) => setProviderEndpoint(event.target.value)} placeholder={providerKind === "preview" ? "https://preview.example.com/v1/render" : "https://analysis.example.com/v1/review"} /></div> : <fieldset className="grid gap-2"><legend className="text-sm font-medium">Verified seed inboxes</legend>{(warmupAccounts.data ?? []).filter((account) => account.enabled && account.verified).map((account) => <label key={account.id} className="flex items-center gap-2 rounded-md border p-2 text-sm"><input type="checkbox" checked={seedAccountIds.includes(account.id)} onChange={(event) => setSeedAccountIds((current) => event.target.checked ? [...current, account.id] : current.filter((id) => id !== account.id))} /><span className="min-w-0 truncate">{account.name} ({account.email})</span></label>)}{warmupAccounts.data?.filter((account) => account.enabled && account.verified).length === 0 && <p className="text-xs text-muted-foreground">Verify at least one enabled warmup account in Admin before configuring placement.</p>}</fieldset>}{providerKind !== "placement" && <div><Label htmlFor="provider-secret">Bearer secret</Label><Input id="provider-secret" type="password" value={providerSecret} onChange={(event) => setProviderSecret(event.target.value)} autoComplete="new-password" /></div>}<Button size="sm" disabled={createProvider.isPending || (providerKind === "placement" && seedAccountIds.length === 0)}>Add provider</Button></form></details>
            </CardContent></Card>
          </div>
        </div>

        <Card><CardHeader><CardTitle>Deployment capabilities</CardTitle></CardHeader><CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{(capabilities.data?.capabilities ?? []).map((item) => <div key={item.id} className="rounded-lg border p-4"><div className="flex items-center justify-between gap-2"><p className="font-semibold">{item.title}</p><Badge variant={item.status === "available" ? "default" : "secondary"}>{item.status.replace("_", " ")}</Badge></div><p className="mt-2 text-sm text-muted-foreground">{item.description}</p>{item.reason && <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">{item.reason}</p>}</div>)}</CardContent></Card>
      </div>
    </div>
  );
}
