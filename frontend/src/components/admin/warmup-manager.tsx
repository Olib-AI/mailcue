import { useState, type FormEvent } from "react";
import { Activity, CheckCircle2, Eraser, Pause, Pencil, Play, Plus, ShieldCheck, Square, Trash2, XCircle } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useMailboxes } from "@/hooks/use-mailboxes";
import {
  useCheckWarmupAccount,
  useClearWarmupMailbox,
  useControlWarmupCampaign,
  useCreateWarmupAccount,
  useCreateWarmupCampaign,
  useDeleteWarmupAccount,
  useToggleWarmupAccount,
  useUpdateWarmupCampaign,
  useWarmupAccounts,
  useWarmupCampaigns,
  useWarmupEvents,
  useWarmupProviderStates,
  useResumeWarmupProvider,
} from "@/hooks/use-warmup";
import type { CreateWarmupAccountRequest, CreateWarmupCampaignRequest, WarmupCampaign } from "@/types/api";

const PRESETS: Record<string, Partial<CreateWarmupAccountRequest>> = {
  gmail: { smtp_host: "smtp.gmail.com", smtp_port: 587, smtp_security: "starttls", imap_host: "imap.gmail.com", imap_port: 993, imap_security: "ssl" },
  yahoo: { smtp_host: "smtp.mail.yahoo.com", smtp_port: 587, smtp_security: "starttls", imap_host: "imap.mail.yahoo.com", imap_port: 993, imap_security: "ssl" },
  icloud: { smtp_host: "smtp.mail.me.com", smtp_port: 587, smtp_security: "starttls", imap_host: "imap.mail.me.com", imap_port: 993, imap_security: "ssl" },
  outlook: { smtp_host: "smtp-mail.outlook.com", smtp_port: 587, smtp_security: "starttls", imap_host: "outlook.office365.com", imap_port: 993, imap_security: "ssl" },
};

const emptyAccount: CreateWarmupAccountRequest = {
  name: "", email: "", provider: "gmail", smtp_host: "smtp.gmail.com", smtp_port: 587,
  smtp_security: "starttls", imap_host: "imap.gmail.com", imap_port: 993,
  imap_security: "ssl", username: "", password: "", enabled: true, ownership_confirmed: false,
};

const defaultCampaign: CreateWarmupCampaignRequest = {
  name: "Domain warmup", local_address: "", account_ids: [], start_daily_volume: 3,
  daily_ramp: 1, max_daily_volume: 20, min_delay_minutes: 30, max_delay_minutes: 120,
  reply_rate: 70, active_hour_start: 8, active_hour_end: 20,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  auto_clean_local_mailbox: false,
};

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong";
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="space-y-1.5"><Label>{label}</Label>{children}</div>;
}

export function WarmupManager() {
  const [showAccountForm, setShowAccountForm] = useState(false);
  const [showCampaignForm, setShowCampaignForm] = useState(false);
  const [editingCampaignId, setEditingCampaignId] = useState<string | null>(null);
  const [accountForm, setAccountForm] = useState(emptyAccount);
  const [campaignForm, setCampaignForm] = useState(defaultCampaign);
  const { data: accounts = [] } = useWarmupAccounts();
  const { data: campaigns = [] } = useWarmupCampaigns();
  const { data: events = [] } = useWarmupEvents();
  const { data: providerStates = [] } = useWarmupProviderStates();
  const { data: mailboxData } = useMailboxes();
  const createAccount = useCreateWarmupAccount();
  const checkAccount = useCheckWarmupAccount();
  const toggleAccount = useToggleWarmupAccount();
  const deleteAccount = useDeleteWarmupAccount();
  const createCampaign = useCreateWarmupCampaign();
  const updateCampaign = useUpdateWarmupCampaign();
  const controlCampaign = useControlWarmupCampaign();
  const clearMailbox = useClearWarmupMailbox();
  const resumeProvider = useResumeWarmupProvider();

  const setAccount = <K extends keyof CreateWarmupAccountRequest>(key: K, value: CreateWarmupAccountRequest[K]) =>
    setAccountForm((current) => ({ ...current, [key]: value }));
  const setCampaign = <K extends keyof CreateWarmupCampaignRequest>(key: K, value: CreateWarmupCampaignRequest[K]) =>
    setCampaignForm((current) => ({ ...current, [key]: value }));

  const chooseProvider = (provider: string) => {
    setAccountForm((current) => ({ ...current, provider, ...(PRESETS[provider] ?? {}) }));
  };

  const submitAccount = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const created = await createAccount.mutateAsync(accountForm);
      toast.success("External account added", { description: "Test both connections before using it." });
      setAccountForm(emptyAccount);
      setShowAccountForm(false);
      await checkAccount.mutateAsync(created.id).then((result) => {
        if (result.ok) toast.success("SMTP and IMAP verified");
        else toast.error("Connection test failed", { description: result.message });
      });
    } catch (error) { toast.error("Could not add account", { description: errorMessage(error) }); }
  };

  const submitCampaign = async (event: FormEvent) => {
    event.preventDefault();
    try {
      if (editingCampaignId) {
        await updateCampaign.mutateAsync({ id: editingCampaignId, body: campaignForm });
        toast.success("Warmup campaign updated");
      } else {
        await createCampaign.mutateAsync(campaignForm);
        toast.success("Warmup campaign created", { description: "Review it, then start when ready." });
      }
      setCampaignForm(defaultCampaign);
      setEditingCampaignId(null);
      setShowCampaignForm(false);
    } catch (error) { toast.error(`Could not ${editingCampaignId ? "update" : "create"} campaign`, { description: errorMessage(error) }); }
  };

  const openNewCampaign = () => {
    setCampaignForm(defaultCampaign);
    setEditingCampaignId(null);
    setShowCampaignForm(true);
  };

  const openCampaignEditor = (campaign: WarmupCampaign) => {
    setCampaignForm({
      name: campaign.name,
      local_address: campaign.local_address,
      account_ids: [...campaign.account_ids],
      start_daily_volume: campaign.start_daily_volume,
      daily_ramp: campaign.daily_ramp,
      max_daily_volume: campaign.max_daily_volume,
      min_delay_minutes: campaign.min_delay_minutes,
      max_delay_minutes: campaign.max_delay_minutes,
      reply_rate: campaign.reply_rate,
      active_hour_start: campaign.active_hour_start,
      active_hour_end: campaign.active_hour_end,
      timezone: campaign.timezone,
      auto_clean_local_mailbox: campaign.auto_clean_local_mailbox,
    });
    setEditingCampaignId(campaign.id);
    setShowCampaignForm(true);
  };

  const closeCampaignForm = () => {
    setCampaignForm(defaultCampaign);
    setEditingCampaignId(null);
    setShowCampaignForm(false);
  };

  const control = async (id: string, action: "start" | "pause" | "stop") => {
    try {
      await controlCampaign.mutateAsync({ id, action });
      toast.success(action === "start" ? "Warmup running" : action === "pause" ? "Warmup paused" : "Warmup stopped");
    } catch (error) { toast.error("Could not update campaign", { description: errorMessage(error) }); }
  };

  return (
    <div className="space-y-6">
      <Card className="border-primary/20 bg-primary/5">
        <CardHeader className="pb-4">
          <div className="flex items-start gap-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 text-primary" />
            <div><CardTitle>Email reputation warmup</CardTitle><CardDescription className="mt-2 max-w-3xl">
              Build legitimate history between your MailCue domain and administrator-owned external mailboxes. Volume rises gradually, timing is randomized, and traffic runs in both directions. Warmup supports good sending practice but cannot guarantee inbox placement.
            </CardDescription></div>
          </div>
        </CardHeader>
      </Card>

      <section className="space-y-3">
        <div className="flex items-center justify-between"><div><h2 className="text-lg font-semibold">External accounts</h2><p className="text-sm text-muted-foreground">Use provider app passwords, not primary passwords.</p></div>
          <Button size="sm" onClick={() => setShowAccountForm((value) => !value)}><Plus />Add account</Button>
        </div>
        {showAccountForm && <Card><CardContent className="pt-6"><form onSubmit={submitAccount} className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <Field label="Provider"><Select value={accountForm.provider} onChange={(e) => chooseProvider(e.target.value)}><option value="gmail">Gmail</option><option value="yahoo">Yahoo</option><option value="icloud">iCloud</option><option value="outlook">Outlook / Microsoft</option><option value="custom">Custom</option></Select></Field>
            <Field label="Label"><Input required value={accountForm.name} onChange={(e) => setAccount("name", e.target.value)} placeholder="Operations Gmail" /></Field>
            <Field label="Email"><Input required type="email" value={accountForm.email} onChange={(e) => { setAccount("email", e.target.value); if (!accountForm.username) setAccount("username", e.target.value); }} /></Field>
            <Field label="SMTP host"><Input required value={accountForm.smtp_host} onChange={(e) => setAccount("smtp_host", e.target.value)} /></Field>
            <Field label="SMTP port"><Input required type="number" value={accountForm.smtp_port} onChange={(e) => setAccount("smtp_port", Number(e.target.value))} /></Field>
            <Field label="SMTP security"><Select value={accountForm.smtp_security} onChange={(e) => setAccount("smtp_security", e.target.value as CreateWarmupAccountRequest["smtp_security"])}><option value="starttls">STARTTLS</option><option value="ssl">TLS / SSL</option><option value="plain">Plain</option></Select></Field>
            <Field label="IMAP host"><Input required value={accountForm.imap_host} onChange={(e) => setAccount("imap_host", e.target.value)} /></Field>
            <Field label="IMAP port"><Input required type="number" value={accountForm.imap_port} onChange={(e) => setAccount("imap_port", Number(e.target.value))} /></Field>
            <Field label="IMAP security"><Select value={accountForm.imap_security} onChange={(e) => setAccount("imap_security", e.target.value as CreateWarmupAccountRequest["imap_security"])}><option value="ssl">TLS / SSL</option><option value="starttls">STARTTLS</option><option value="plain">Plain</option></Select></Field>
            <Field label="Username"><Input required value={accountForm.username} onChange={(e) => setAccount("username", e.target.value)} /></Field>
            <Field label="App password"><Input required type="password" autoComplete="new-password" value={accountForm.password} onChange={(e) => setAccount("password", e.target.value)} /></Field>
          </div>
          <div className="flex items-center gap-2"><Checkbox checked={accountForm.ownership_confirmed} onCheckedChange={(value) => setAccount("ownership_confirmed", value)} /><Label>I own or am authorized to use this mailbox for warmup traffic.</Label></div>
          <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => setShowAccountForm(false)}>Cancel</Button><Button type="submit" disabled={createAccount.isPending || !accountForm.ownership_confirmed}>Add and test</Button></div>
        </form></CardContent></Card>}
        <div className="grid gap-3 md:grid-cols-2">
          {accounts.map((account) => <Card key={account.id}><CardContent className="flex items-start justify-between gap-3 pt-6"><div className="min-w-0"><div className="flex items-center gap-2"><span className="truncate font-medium">{account.name}</span><Badge variant={account.verified ? "default" : "secondary"}>{account.verified ? "Verified" : "Needs test"}</Badge>{!account.enabled && <Badge variant="outline">Disabled</Badge>}</div><p className="mt-1 truncate text-sm text-muted-foreground">{account.email} · {account.provider}</p>{account.last_error && <p className="mt-2 line-clamp-2 text-xs text-destructive">{account.last_error}</p>}</div>
            <div className="flex shrink-0 gap-1"><Button size="sm" variant="outline" onClick={() => void checkAccount.mutateAsync(account.id).then((r) => r.ok ? toast.success("Connections verified") : toast.error(r.message))}>Test</Button><Button size="icon" variant="ghost" aria-label={account.enabled ? "Disable account" : "Enable account"} onClick={() => toggleAccount.mutate({ id: account.id, enabled: !account.enabled })}>{account.enabled ? <Pause /> : <Play />}</Button><Button size="icon" variant="ghost" aria-label="Delete account" onClick={() => { if (window.confirm(`Delete ${account.email}?`)) deleteAccount.mutate(account.id); }}><Trash2 /></Button></div>
          </CardContent></Card>)}
          {accounts.length === 0 && <p className="text-sm text-muted-foreground">No external accounts configured.</p>}
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between"><div><h2 className="text-lg font-semibold">Campaigns</h2><p className="text-sm text-muted-foreground">Daily caps count MailCue outbound messages; replies are tracked separately.</p></div><Button size="sm" onClick={openNewCampaign} disabled={!accounts.some((a) => a.verified && a.enabled)}><Plus />New campaign</Button></div>
        {showCampaignForm && <Card><CardContent className="pt-6"><form onSubmit={submitCampaign} className="space-y-5">
          <div><h3 className="font-semibold">{editingCampaignId ? "Edit campaign" : "New campaign"}</h3>{editingCampaignId && <p className="mt-1 text-sm text-muted-foreground">Changes apply to the next scheduled message without resetting campaign progress.</p>}</div>
          <div className="grid gap-4 md:grid-cols-3">
            <Field label="Campaign name"><Input required value={campaignForm.name} onChange={(e) => setCampaign("name", e.target.value)} /></Field>
            <Field label="MailCue sender"><Select required value={campaignForm.local_address} onChange={(e) => setCampaign("local_address", e.target.value)}><option value="">Select mailbox</option>{mailboxData?.mailboxes.map((mailbox) => <option key={mailbox.address} value={mailbox.address}>{mailbox.address}</option>)}</Select></Field>
            <Field label="Timezone"><Input required value={campaignForm.timezone} onChange={(e) => setCampaign("timezone", e.target.value)} /></Field>
          </div>
          <div><Label>Participating external accounts</Label><div className="mt-2 flex flex-wrap gap-4">{accounts.map((account) => { const checked = campaignForm.account_ids.includes(account.id); const available = account.verified && account.enabled; return <label key={account.id} className={`flex items-center gap-2 text-sm ${available ? "" : "text-muted-foreground"}`}><Checkbox checked={checked} disabled={!available && !checked} onCheckedChange={(nextChecked) => setCampaign("account_ids", nextChecked ? [...campaignForm.account_ids, account.id] : campaignForm.account_ids.filter((id) => id !== account.id))} />{account.email}{!available && <span className="text-xs">({account.enabled ? "needs test" : "disabled"})</span>}</label>; })}</div></div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Starting messages / day"><Input type="number" min={1} max={100} value={campaignForm.start_daily_volume} onChange={(e) => setCampaign("start_daily_volume", Number(e.target.value))} /></Field>
            <Field label="Daily increase"><Input type="number" min={0} max={50} value={campaignForm.daily_ramp} onChange={(e) => setCampaign("daily_ramp", Number(e.target.value))} /></Field>
            <Field label="Maximum / day"><Input type="number" min={1} max={200} value={campaignForm.max_daily_volume} onChange={(e) => setCampaign("max_daily_volume", Number(e.target.value))} /></Field>
            <Field label="Reply rate %"><Input type="number" min={0} max={100} value={campaignForm.reply_rate} onChange={(e) => setCampaign("reply_rate", Number(e.target.value))} /></Field>
            <Field label="Minimum delay (minutes)"><Input type="number" min={5} value={campaignForm.min_delay_minutes} onChange={(e) => setCampaign("min_delay_minutes", Number(e.target.value))} /></Field>
            <Field label="Maximum delay (minutes)"><Input type="number" min={5} value={campaignForm.max_delay_minutes} onChange={(e) => setCampaign("max_delay_minutes", Number(e.target.value))} /></Field>
            <Field label="Active from (hour)"><Input type="number" min={0} max={23} value={campaignForm.active_hour_start} onChange={(e) => setCampaign("active_hour_start", Number(e.target.value))} /></Field>
            <Field label="Active until (hour)"><Input type="number" min={1} max={24} value={campaignForm.active_hour_end} onChange={(e) => setCampaign("active_hour_end", Number(e.target.value))} /></Field>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox id="auto-clean-local" checked={campaignForm.auto_clean_local_mailbox ?? false} onCheckedChange={(val) => setCampaign("auto_clean_local_mailbox", Boolean(val))} />
            <Label htmlFor="auto-clean-local" className="cursor-pointer text-sm font-normal">Auto-clean warmup emails from local mailbox (automatically purges sent & received warmup traffic after each run)</Label>
          </div>
          <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={closeCampaignForm}>Cancel</Button><Button type="submit" disabled={createCampaign.isPending || updateCampaign.isPending || campaignForm.account_ids.length === 0 || !campaignForm.local_address}>{editingCampaignId ? "Save changes" : "Create campaign"}</Button></div>
        </form></CardContent></Card>}
        <div className="space-y-3">{campaigns.map((campaign) => <Card key={campaign.id}><CardContent className="pt-6"><div className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex items-center gap-2"><h3 className="font-semibold">{campaign.name}</h3><Badge variant={campaign.status === "active" ? "default" : "secondary"}>{campaign.status}</Badge></div><p className="mt-1 text-sm text-muted-foreground">{campaign.local_address} · {campaign.messages_sent_today} outbound today · {campaign.total_sent} conversation messages · {campaign.total_failed} failed</p><p className="mt-1 text-xs text-muted-foreground">Plan: {campaign.start_daily_volume}/day +{campaign.daily_ramp}/day, capped at {campaign.max_daily_volume}; {campaign.min_delay_minutes}–{campaign.max_delay_minutes} min jitter</p></div>
            <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => openCampaignEditor(campaign)}><Pencil />Edit</Button><Button size="sm" variant="outline" disabled={clearMailbox.isPending} onClick={() => { if (window.confirm(`Purge sent and received warmup emails for ${campaign.name} from ${campaign.local_address}?`)) { void clearMailbox.mutateAsync(campaign.id).then((r) => toast.success(`Cleared ${r.deleted_count} warmup emails from ${campaign.local_address}`)).catch((err) => toast.error(errorMessage(err))); } }}><Eraser />Clear Mailbox</Button>{campaign.status !== "active" && <Button size="sm" onClick={() => void control(campaign.id, "start")}><Play />{campaign.status === "paused" ? "Resume" : "Start"}</Button>}{campaign.status === "active" && <Button size="sm" variant="outline" onClick={() => void control(campaign.id, "pause")}><Pause />Pause</Button>}{campaign.status !== "stopped" && <Button size="sm" variant="destructive" onClick={() => void control(campaign.id, "stop")}><Square />Stop</Button>}</div></div></CardContent></Card>)}{campaigns.length === 0 && <p className="text-sm text-muted-foreground">No warmup campaigns yet.</p>}</div>
      </section>

      <section className="space-y-3"><div><h2 className="text-lg font-semibold">Provider health</h2><p className="text-sm text-muted-foreground">Outbound volume is balanced per ISP. Deferrals cool down automatically; permanent failures require review.</p></div><div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">{providerStates.map((state) => <Card key={state.id}><CardContent className="pt-6"><div className="flex items-center justify-between"><span className="font-semibold capitalize">{state.provider}</span><Badge variant={state.status === "healthy" ? "default" : state.status === "blocked" ? "destructive" : "secondary"}>{state.status}</Badge></div><p className="mt-3 text-sm">{state.sent_today} outbound today · {state.failed_today} failed</p>{state.paused_until && <p className="mt-1 text-xs text-muted-foreground">Retry after {new Date(state.paused_until).toLocaleString()}</p>}{state.last_response && <p className="mt-2 line-clamp-2 text-xs text-destructive">{state.last_smtp_code ?? state.last_enhanced_status}: {state.last_response}</p>}{state.status === "blocked" && <Button className="mt-3" size="sm" variant="outline" onClick={() => resumeProvider.mutate(state.id)}>Resume after fix</Button>}</CardContent></Card>)}{providerStates.length === 0 && <p className="text-sm text-muted-foreground">Provider health appears after a campaign is created.</p>}</div></section>

      <section className="space-y-3"><div className="flex items-center gap-2"><Activity className="h-5 w-5" /><h2 className="text-lg font-semibold">Recent activity</h2></div><Card><CardContent className="pt-6"><div className="divide-y">{events.slice(0, 5).map((event) => <div key={event.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">{event.status === "sent" ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <XCircle className="h-4 w-4 text-destructive" />}<div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{event.subject}</p><p className="text-xs text-muted-foreground">{event.direction === "local_to_external" ? `MailCue → ${event.provider ?? "external"}` : event.direction === "external_to_local" ? `${event.provider ?? "External"} → MailCue` : `${event.provider ?? "Provider"} delivery feedback`} · {new Date(event.created_at).toLocaleString()}</p></div>{event.error && <span className="max-w-xs truncate text-xs text-destructive">{event.smtp_code ?? event.enhanced_status ?? "Error"}: {event.error}</span>}</div>)}{events.length === 0 && <p className="text-sm text-muted-foreground">No deliveries yet.</p>}</div></CardContent></Card></section>
    </div>
  );
}
