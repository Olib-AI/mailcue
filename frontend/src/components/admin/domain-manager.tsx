import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
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
  useAddDomain,
  useRemoveDomain,
  useVerifyDns,
} from "@/hooks/use-domains";
import type { Domain } from "@/types/api";

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
  const removeDomain = useRemoveDomain();
  const verifyDns = useVerifyDns();
  const { data: detail, isLoading: detailLoading } = useDomainDetail(domain.name);

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

  const copyToClipboard = (text: string) => {
    void navigator.clipboard.writeText(text);
    toast.success("Copied to clipboard");
  };

  return (
    <>
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Globe className="h-5 w-5 text-muted-foreground" />
              <CardTitle className="text-base">{domain.name}</CardTitle>
              {domain.all_verified && (
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
        </CardHeader>
        <CardContent className="space-y-3">
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
            <div className="space-y-3">
              {detailLoading ? (
                <div className="flex justify-center py-4">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : detail ? (
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
                        {(detail.dns_records ?? []).map((record, idx) => (
                          <tr key={`${record.record_type}-${record.hostname}-${idx}`} className="border-b last:border-0">
                            <td className="px-3 py-2">
                              <Badge variant="outline">{record.record_type}</Badge>
                            </td>
                            <td className="px-3 py-2 font-mono text-xs break-all">
                              {record.hostname}
                            </td>
                            <td className="px-3 py-2">
                              <div className="font-mono text-xs break-all max-w-xs">
                                {record.expected_value}
                              </div>
                              {record.purpose && (
                                <div className="text-xs text-muted-foreground mt-0.5">
                                  {record.purpose}
                                </div>
                              )}
                            </td>
                            <td className="px-3 py-2">
                              {record.record_type === "PTR" || record.record_type === "A" ? (
                                <span className="text-xs text-muted-foreground">Info</span>
                              ) : record.verified ? (
                                <CheckCircle className="h-4 w-4 text-green-600" />
                              ) : (
                                <XCircle className="h-4 w-4 text-destructive" />
                              )}
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
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* DKIM public key */}
                  {detail.dkim_public_key_txt && (
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
