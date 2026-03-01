import { useEffect, useState } from "react";
import {
  Loader2,
  Server,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  useServerSettings,
  useUpdateServerSettings,
} from "@/hooks/use-server-settings";
import {
  useTlsCertificateStatus,
  useUploadTlsCertificate,
} from "@/hooks/use-tls-certificate";

function ServerHostnameCard() {
  const { data: settings, isLoading } = useServerSettings();
  const updateSettings = useUpdateServerSettings();
  const [hostname, setHostname] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (settings?.hostname) {
      setHostname(settings.hostname);
    }
  }, [settings?.hostname]);

  const handleSave = () => {
    updateSettings.mutate(
      { hostname },
      {
        onSuccess: () => {
          toast.success("Server hostname updated");
          setDirty(false);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to update hostname"
          );
        },
      }
    );
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Server className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">Server Hostname</CardTitle>
        </div>
        <CardDescription>
          This hostname appears in MX and SPF records for all managed domains.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <div className="flex items-center gap-2">
            <Input
              value={hostname}
              onChange={(e) => {
                setHostname(e.target.value);
                setDirty(e.target.value !== settings?.hostname);
              }}
              placeholder="mail.example.com"
              className="max-w-sm font-mono text-sm"
            />
            <Button
              onClick={handleSave}
              disabled={!dirty || updateSettings.isPending}
              size="sm"
            >
              {updateSettings.isPending && (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              )}
              Save
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function TlsCertificateCard() {
  const { data: status, isLoading } = useTlsCertificateStatus();
  const uploadCert = useUploadTlsCertificate();
  const [certificate, setCertificate] = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [caCertificate, setCaCertificate] = useState("");

  const handleFileRead = (
    setter: (value: string) => void,
  ) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pem,.crt,.key,.cer";
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => setter(reader.result as string);
      reader.readAsText(file);
    };
    input.click();
  };

  const handleUpload = () => {
    uploadCert.mutate(
      {
        certificate,
        private_key: privateKey,
        ...(caCertificate ? { ca_certificate: caCertificate } : {}),
      },
      {
        onSuccess: () => {
          toast.success("TLS certificate uploaded successfully");
          setCertificate("");
          setPrivateKey("");
          setCaCertificate("");
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to upload certificate"
          );
        },
      }
    );
  };

  const formatDate = (iso: string | null) => {
    if (!iso) return "\u2014";
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">TLS Certificate</CardTitle>
          </div>
          {!isLoading && (
            status?.configured ? (
              <Badge className="bg-green-600 text-white">Configured</Badge>
            ) : (
              <Badge variant="secondary">Self-signed</Badge>
            )
          )}
        </div>
        <CardDescription>
          Upload a custom TLS certificate for Postfix and Dovecot.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <>
            {/* Metadata summary when configured */}
            {status?.configured && (
              <div className="rounded-md border p-3 space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Common Name</span>
                  <span className="font-mono">{status.common_name ?? "\u2014"}</span>
                </div>
                {status.san_dns_names.length > 0 && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">SANs</span>
                    <span className="font-mono text-right">
                      {status.san_dns_names.join(", ")}
                    </span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Expires</span>
                  <span>{formatDate(status.not_after)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Fingerprint</span>
                  <span className="font-mono text-xs truncate max-w-[240px]">
                    {status.fingerprint_sha256 ?? "\u2014"}
                  </span>
                </div>
              </div>
            )}

            {/* Upload form */}
            <div className="space-y-3">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label>Server Certificate (PEM)</Label>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 text-xs"
                    onClick={() => handleFileRead(setCertificate)}
                  >
                    <Upload className="mr-1 h-3 w-3" />
                    Browse
                  </Button>
                </div>
                <Textarea
                  value={certificate}
                  onChange={(e) => setCertificate(e.target.value)}
                  placeholder="-----BEGIN CERTIFICATE-----"
                  rows={6}
                  className="font-mono text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label>Private Key (PEM)</Label>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 text-xs"
                    onClick={() => handleFileRead(setPrivateKey)}
                  >
                    <Upload className="mr-1 h-3 w-3" />
                    Browse
                  </Button>
                </div>
                <Textarea
                  value={privateKey}
                  onChange={(e) => setPrivateKey(e.target.value)}
                  placeholder="-----BEGIN PRIVATE KEY-----"
                  rows={6}
                  className="font-mono text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label>
                    CA / Intermediate Chain (PEM){" "}
                    <span className="text-muted-foreground">(optional)</span>
                  </Label>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 text-xs"
                    onClick={() => handleFileRead(setCaCertificate)}
                  >
                    <Upload className="mr-1 h-3 w-3" />
                    Browse
                  </Button>
                </div>
                <Textarea
                  value={caCertificate}
                  onChange={(e) => setCaCertificate(e.target.value)}
                  placeholder="-----BEGIN CERTIFICATE-----"
                  rows={6}
                  className="font-mono text-xs"
                />
              </div>

              <Button
                onClick={handleUpload}
                disabled={!certificate || !privateKey || uploadCert.isPending}
              >
                {uploadCert.isPending && (
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                )}
                Upload Certificate
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function MailServerManager() {
  return (
    <div className="space-y-4">
      <ServerHostnameCard />
      <TlsCertificateCard />
    </div>
  );
}

export { MailServerManager };
