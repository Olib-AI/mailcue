import { useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  AlertTriangle,
  CheckCircle,
  XCircle,
  Loader2,
  Plus,
  Trash2,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Copy,
  Globe,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  useDomains,
  useDomainDetail,
  useDnsState,
  useAddDomain,
  useRemoveDomain,
  useVerifyDns,
} from "@/hooks/use-domains";
import type { DnsRecordInfo, Domain } from "@/types/api";

// =============================================================================
// Helpers
// =============================================================================

/** Format an ISO timestamp as a short relative string ("12s ago", "4h ago"). */
function formatRelative(iso: string | null | undefined, now: number): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const diffMs = Math.max(0, now - t);
  const sec = Math.round(diffMs / 1000);
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.round(hr / 24);
  return `${days}d ago`;
}

/** Truncate a value for display while keeping the head + tail visible. */
function truncateMiddle(value: string, max = 64): string {
  if (value.length <= max) return value;
  const head = Math.ceil((max - 3) / 2);
  const tail = Math.floor((max - 3) / 2);
  return `${value.slice(0, head)}...${value.slice(-tail)}`;
}

/** Records that are informational only (PTR / A) and can never "drift". */
function isInfoRecord(record: Pick<DnsRecordInfo, "record_type">): boolean {
  return record.record_type === "PTR" || record.record_type === "A";
}

type RecordStatus = "info" | "verified" | "drift" | "missing";

function recordStatus(record: DnsRecordInfo): RecordStatus {
  if (isInfoRecord(record)) return "info";
  if (record.drift === true) return "drift";
  if (record.verified) return "verified";
  if (record.current_value === null || record.current_value === undefined) {
    return "missing";
  }
  // Has a current value, not flagged as drift, but not verified — treat as drift.
  return "drift";
}

function RecordStatusBadge({ status }: { status: RecordStatus }) {
  switch (status) {
    case "verified":
      return (
        <Badge className="bg-green-600 text-white hover:bg-green-600">
          Verified
        </Badge>
      );
    case "drift":
      return <Badge variant="destructive">Drift</Badge>;
    case "missing":
      return (
        <Badge className="border-transparent bg-amber-500 text-white hover:bg-amber-500">
          Missing
        </Badge>
      );
    case "info":
      return <Badge variant="secondary">Info</Badge>;
  }
}

const addDomainSchema = z.object({
  name: z
    .string()
    .min(1, "Domain name is required")
    .regex(
      /^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$/,
      "Invalid domain name"
    ),
  dkim_selector: z.string().optional(),
});

type AddDomainValues = z.infer<typeof addDomainSchema>;

function DnsStatusBadge({
  label,
  verified,
}: {
  label: string;
  verified: boolean;
}) {
  return (
    <div className="flex items-center gap-1">
      {verified ? (
        <CheckCircle className="h-4 w-4 text-green-600" />
      ) : (
        <XCircle className="h-4 w-4 text-destructive" />
      )}
      <span className="text-xs">{label}</span>
    </div>
  );
}

function DomainCard({ domain }: { domain: Domain }) {
  const [expanded, setExpanded] = useState(true);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [comparingRows, setComparingRows] = useState<Record<string, boolean>>({});
  const recordsAnchorRef = useRef<HTMLDivElement | null>(null);
  const removeDomain = useRemoveDomain();
  const verifyDns = useVerifyDns();
  const { data: detail, isLoading: detailLoading } = useDomainDetail(domain.name);
  const dnsState = useDnsState(domain.name);

  // Tick a "now" timestamp every 15s so relative times re-render without
  // re-fetching. Cheap, scoped to the mounted card.
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(id);
  }, []);

  // Prefer the polled dns-state records (they include drift + timestamps).
  // Fall back to the detail endpoint if dns-state is unavailable (404 etc.).
  const records: DnsRecordInfo[] = useMemo(() => {
    if (dnsState.data?.records && dnsState.data.records.length > 0) {
      return dnsState.data.records;
    }
    return detail?.dns_records ?? [];
  }, [dnsState.data, detail]);

  const driftingTypes = useMemo(() => {
    const types = new Set<string>();
    for (const r of records) {
      if (isInfoRecord(r)) continue;
      if (r.drift === true) types.add(r.record_type);
    }
    return Array.from(types);
  }, [records]);

  const missingTypes = useMemo(() => {
    const types = new Set<string>();
    for (const r of records) {
      if (isInfoRecord(r)) continue;
      if (r.drift === true) continue;
      if (!r.verified && (r.current_value === null || r.current_value === undefined)) {
        types.add(r.record_type);
      }
    }
    return Array.from(types);
  }, [records]);

  // Trust dns-state's flags when present; otherwise infer from per-record data.
  const hasDrift = dnsState.data?.has_drift ?? driftingTypes.length > 0;
  const hasMissing = dnsState.data?.has_missing ?? missingTypes.length > 0;

  const lastPolledAt = dnsState.dataUpdatedAt;
  const lastPolledIso = lastPolledAt ? new Date(lastPolledAt).toISOString() : null;

  const handleVerify = () => {
    verifyDns.mutate(domain.name, {
      onSuccess: (result) => {
        if (result.all_verified) {
          toast.success(`All DNS records verified for ${domain.name}`);
        } else {
          toast.info("DNS check complete. Some records are not yet configured.");
        }
      },
      onError: (err) => {
        toast.error(
          err instanceof Error ? err.message : "DNS verification failed"
        );
      },
    });
  };

  const handleShowDetails = () => {
    setExpanded(true);
    // Defer to next paint so the records section is in the DOM.
    window.requestAnimationFrame(() => {
      recordsAnchorRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  };

  const handleDelete = () => {
    removeDomain.mutate(domain.name, {
      onSuccess: () => {
        toast.success(`Domain ${domain.name} removed`);
        setDeleteConfirm(false);
      },
      onError: (err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to remove domain"
        );
      },
    });
  };

  const copyToClipboard = (text: string, label?: string) => {
    void navigator.clipboard.writeText(text);
    toast.success(label ? `${label} copied` : "Copied to clipboard");
  };

  const toggleCompare = (rowKey: string) => {
    setComparingRows((prev) => ({ ...prev, [rowKey]: !prev[rowKey] }));
  };

  return (
    <>
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Globe className="h-5 w-5 text-muted-foreground" />
              <CardTitle className="text-base">{domain.name}</CardTitle>
              {domain.all_verified && !hasDrift && (
                <Badge className="bg-green-600 text-white">Verified</Badge>
              )}
            </div>
            <div className="flex items-center gap-1">
              <Button
                size="sm"
                variant="outline"
                onClick={handleVerify}
                disabled={verifyDns.isPending}
              >
                {verifyDns.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                <span className="ml-1.5 hidden sm:inline">Verify DNS</span>
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setDeleteConfirm(true)}
              >
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </div>
          </div>
          {dnsState.isSuccess && lastPolledIso && (
            <p className="text-xs text-muted-foreground">
              Last polled {formatRelative(lastPolledIso, now) || "just now"}
            </p>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {/* Drift / missing banner — only render when something is wrong. */}
          {hasDrift ? (
            <div
              role="alert"
              className="flex items-start gap-3 rounded-md border border-destructive/50 bg-destructive/10 p-3"
            >
              <AlertTriangle className="h-5 w-5 text-destructive mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0 space-y-1">
                <p className="text-sm font-medium text-destructive">
                  Published DNS records have drifted
                </p>
                <p className="text-xs text-muted-foreground">
                  {driftingTypes.length > 0 ? (
                    <>Drifted: <strong>{driftingTypes.join(", ")}</strong>. </>
                  ) : null}
                  The published value no longer matches what MailCue is
                  signing/expecting. Senders may see authentication failures.
                </p>
                <div className="flex flex-wrap gap-2 pt-1">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleVerify}
                    disabled={verifyDns.isPending}
                  >
                    {verifyDns.isPending ? (
                      <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                    ) : (
                      <RefreshCw className="mr-1.5 h-3 w-3" />
                    )}
                    Re-check now
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={handleShowDetails}
                  >
                    Show details
                  </Button>
                </div>
              </div>
            </div>
          ) : hasMissing ? (
            <div
              role="alert"
              className="flex items-start gap-3 rounded-md border border-amber-500/50 bg-amber-500/10 p-3"
            >
              <AlertTriangle className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0 space-y-1">
                <p className="text-sm font-medium">
                  Some records are not published yet
                </p>
                <p className="text-xs text-muted-foreground">
                  {missingTypes.length > 0
                    ? `Awaiting: ${missingTypes.join(", ")}.`
                    : "Publish the records below in your DNS provider, then re-check."}
                </p>
                <div className="flex flex-wrap gap-2 pt-1">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={handleVerify}
                    disabled={verifyDns.isPending}
                  >
                    {verifyDns.isPending ? (
                      <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                    ) : (
                      <RefreshCw className="mr-1.5 h-3 w-3" />
                    )}
                    Re-check now
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={handleShowDetails}
                  >
                    Show details
                  </Button>
                </div>
              </div>
            </div>
          ) : null}

          {/* DNS Status Badges */}
          <div className="flex flex-wrap gap-3">
            <DnsStatusBadge label="MX" verified={domain.mx_verified} />
            <DnsStatusBadge label="SPF" verified={domain.spf_verified} />
            <DnsStatusBadge label="DKIM" verified={domain.dkim_verified} />
            <DnsStatusBadge label="DMARC" verified={domain.dmarc_verified} />
            <DnsStatusBadge label="MTA-STS" verified={domain.mta_sts_verified} />
            <DnsStatusBadge label="TLS-RPT" verified={domain.tls_rpt_verified} />
          </div>

          {/* Expandable DNS records section */}
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-between"
            onClick={() => setExpanded(!expanded)}
          >
            <span className="text-sm">Required DNS Records</span>
            {expanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </Button>

          {expanded && (
            <div className="space-y-3" ref={recordsAnchorRef}>
              {detailLoading && records.length === 0 ? (
                <div className="flex justify-center py-4">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : records.length > 0 ? (
                <>
                  {/* DNS records table */}
                  <div className="overflow-x-auto rounded-md border">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b bg-muted/50">
                          <th className="px-3 py-2 text-left font-medium">Type</th>
                          <th className="px-3 py-2 text-left font-medium">
                            Hostname
                          </th>
                          <th className="px-3 py-2 text-left font-medium">Value</th>
                          <th className="px-3 py-2 text-left font-medium">
                            Status
                          </th>
                          <th className="px-3 py-2 text-left font-medium" />
                        </tr>
                      </thead>
                      <tbody>
                        {records.map((record, idx) => {
                          const rowKey = `${record.record_type}-${record.hostname}-${idx}`;
                          const status = recordStatus(record);
                          const isComparing = comparingRows[rowKey] === true;
                          const showTimestamps =
                            !!record.last_checked_at ||
                            (!record.verified && !!record.last_verified_at);
                          return (
                            <tr key={rowKey} className="border-b last:border-0 align-top">
                              <td className="px-3 py-2">
                                <Badge variant="outline">{record.record_type}</Badge>
                              </td>
                              <td className="px-3 py-2 font-mono text-xs break-all">
                                {record.hostname}
                              </td>
                              <td className="px-3 py-2">
                                <div
                                  className="font-mono text-xs break-all max-w-xs"
                                  title={record.expected_value}
                                >
                                  {record.expected_value}
                                </div>
                                {record.purpose && (
                                  <div className="text-xs text-muted-foreground mt-0.5">
                                    {record.purpose}
                                  </div>
                                )}
                                {status === "drift" && (
                                  <div className="mt-2">
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => toggleCompare(rowKey)}
                                    >
                                      {isComparing ? "Hide compare" : "Compare"}
                                    </Button>
                                  </div>
                                )}
                                {status === "drift" && isComparing && (
                                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                                    <div className="space-y-1">
                                      <div className="flex items-center justify-between gap-2">
                                        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                                          Expected (MailCue)
                                        </span>
                                        <Button
                                          size="sm"
                                          variant="ghost"
                                          className="h-6 px-2 text-xs"
                                          onClick={() =>
                                            copyToClipboard(
                                              record.expected_value,
                                              "Expected value",
                                            )
                                          }
                                        >
                                          <Copy className="mr-1 h-3 w-3" />
                                          Copy expected
                                        </Button>
                                      </div>
                                      <pre
                                        className="whitespace-pre-wrap break-all rounded border bg-muted p-2 font-mono text-[11px]"
                                        title={record.expected_value}
                                      >
                                        {truncateMiddle(record.expected_value, 240)}
                                      </pre>
                                    </div>
                                    <div className="space-y-1">
                                      <div className="flex items-center justify-between gap-2">
                                        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                                          Published (DNS)
                                        </span>
                                        <Button
                                          size="sm"
                                          variant="ghost"
                                          className="h-6 px-2 text-xs"
                                          disabled={!record.current_value}
                                          onClick={() =>
                                            record.current_value &&
                                            copyToClipboard(
                                              record.current_value,
                                              "Published value",
                                            )
                                          }
                                        >
                                          <Copy className="mr-1 h-3 w-3" />
                                          Copy published
                                        </Button>
                                      </div>
                                      <pre
                                        className="whitespace-pre-wrap break-all rounded border border-destructive/40 bg-destructive/5 p-2 font-mono text-[11px]"
                                        title={record.current_value ?? ""}
                                      >
                                        {record.current_value
                                          ? truncateMiddle(record.current_value, 240)
                                          : "(no record published)"}
                                      </pre>
                                      <p className="text-[11px] text-destructive">
                                        This differs from what MailCue expects.
                                      </p>
                                    </div>
                                  </div>
                                )}
                                {showTimestamps && (
                                  <div className="mt-1 text-xs text-muted-foreground">
                                    {record.last_checked_at && (
                                      <span>
                                        Checked {formatRelative(record.last_checked_at, now)}
                                      </span>
                                    )}
                                    {!record.verified &&
                                      record.last_verified_at && (
                                        <span>
                                          {record.last_checked_at ? " · " : ""}
                                          Last verified{" "}
                                          {formatRelative(
                                            record.last_verified_at,
                                            now,
                                          )}{" "}
                                          — has drifted since
                                        </span>
                                      )}
                                  </div>
                                )}
                              </td>
                              <td className="px-3 py-2">
                                <RecordStatusBadge status={status} />
                              </td>
                              <td className="px-3 py-2">
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() =>
                                    copyToClipboard(record.expected_value)
                                  }
                                >
                                  <Copy className="h-3 w-3" />
                                </Button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {/* DKIM public key */}
                  {detail?.dkim_public_key_txt && (
                    <div className="space-y-1.5">
                      <Label>DKIM Public Key Record</Label>
                      <textarea
                        readOnly
                        value={detail.dkim_public_key_txt}
                        className="w-full rounded-md border bg-muted p-2 font-mono text-xs resize-none"
                        rows={4}
                      />
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          copyToClipboard(detail.dkim_public_key_txt ?? "")
                        }
                      >
                        <Copy className="mr-1.5 h-3 w-3" />
                        Copy DKIM Record
                      </Button>
                    </div>
                  )}
                </>
              ) : null}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Delete confirmation dialog */}
      <Dialog open={deleteConfirm} onOpenChange={setDeleteConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove Domain</DialogTitle>
            <DialogDescription>
              Are you sure you want to remove <strong>{domain.name}</strong>?
              This will delete the DKIM keys and remove all mail service
              configuration for this domain.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteConfirm(false)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={removeDomain.isPending}
            >
              {removeDomain.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Remove Domain
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function DomainManager() {
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const { data, isLoading } = useDomains();
  const addDomain = useAddDomain();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<AddDomainValues>({
    resolver: zodResolver(addDomainSchema),
    defaultValues: { name: "", dkim_selector: "mail" },
  });

  const onSubmit = (values: AddDomainValues) => {
    addDomain.mutate(
      { name: values.name, dkim_selector: values.dkim_selector },
      {
        onSuccess: () => {
          toast.success(`Domain ${values.name} added`);
          reset();
          setAddDialogOpen(false);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to add domain"
          );
        },
      }
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Domains</h2>
          <p className="text-sm text-muted-foreground">
            Manage email domains, DKIM keys, and DNS records.
          </p>
        </div>
        <Button onClick={() => setAddDialogOpen(true)}>
          <Plus className="mr-1.5 h-4 w-4" />
          Add Domain
        </Button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : data?.domains.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <CardDescription>
              No domains configured. Add a domain to get started with DKIM
              signing and DNS verification.
            </CardDescription>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {data?.domains.map((domain) => (
            <DomainCard key={domain.id} domain={domain} />
          ))}
        </div>
      )}

      {/* Add Domain Dialog */}
      <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Domain</DialogTitle>
            <DialogDescription>
              Enter the domain name to manage. DKIM keys will be generated
              automatically.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="domain-name">Domain Name</Label>
              <Input
                id="domain-name"
                placeholder="example.com"
                {...register("name")}
              />
              {errors.name && (
                <p className="text-xs text-destructive">
                  {errors.name.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="dkim-selector">
                DKIM Selector{" "}
                <span className="text-muted-foreground">(optional)</span>
              </Label>
              <Input
                id="dkim-selector"
                placeholder="mail"
                {...register("dkim_selector")}
              />
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setAddDialogOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={addDomain.isPending}>
                {addDomain.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Add Domain
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export { DomainManager };
