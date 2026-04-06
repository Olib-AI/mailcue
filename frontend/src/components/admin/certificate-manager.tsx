import { useState } from "react";
import {
  Download,
  Copy,
  Loader2,
  ShieldCheck,
  ShieldAlert,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useCertificateInfo } from "@/hooks/use-certificate";
import type { CertificateDetail } from "@/types/api";

/** Format a key_usage snake_case string into a readable label. */
function formatUsage(s: string): string {
  return s
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function copyToClipboard(text: string, label: string) {
  void navigator.clipboard.writeText(text);
  toast.success(`${label} copied to clipboard`);
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Reusable field row for the detail table. */
function Field({
  label,
  value,
  mono,
  copyable,
}: {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
  copyable?: boolean;
}) {
  if (!value) return null;
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <span className="text-xs font-medium text-muted-foreground shrink-0 w-40">
        {label}
      </span>
      <div className="flex items-center gap-1.5 min-w-0">
        <span
          className={`text-sm break-all text-right ${mono ? "font-mono" : ""}`}
        >
          {value}
        </span>
        {copyable && (
          <button
            type="button"
            className="shrink-0 p-0.5 rounded hover:bg-muted"
            onClick={() => copyToClipboard(value, label)}
          >
            <Copy className="h-3 w-3 text-muted-foreground" />
          </button>
        )}
      </div>
    </div>
  );
}

/** A full certificate card (used for both server and CA). */
function CertificateCard({
  cert,
  title,
  icon,
}: {
  cert: CertificateDetail;
  title: string;
  icon: React.ReactNode;
}) {
  const isExpired = new Date(cert.validity.not_after) < new Date();
  const hasDnsSans = cert.san.dns_names.length > 0;
  const hasIpSans = cert.san.ip_addresses.length > 0;
  const hasEmailSans = cert.san.emails.length > 0;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          {icon}
          <CardTitle className="text-base">{title}</CardTitle>
          {cert.is_ca && (
            <Badge variant="outline" className="text-xs">
              CA
            </Badge>
          )}
          {isExpired ? (
            <Badge variant="destructive">Expired</Badge>
          ) : (
            <Badge className="bg-green-600 text-white">Valid</Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Subject */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
            Subject
          </h4>
          <div className="divide-y">
            <Field label="Common Name (CN)" value={cert.subject.common_name} />
            <Field label="Organization (O)" value={cert.subject.organization} />
            <Field
              label="Organizational Unit (OU)"
              value={cert.subject.organizational_unit}
            />
            <Field label="Locality (L)" value={cert.subject.locality} />
            <Field label="State (ST)" value={cert.subject.state} />
            <Field label="Country (C)" value={cert.subject.country} />
            <Field label="Email" value={cert.subject.email} />
          </div>
        </div>

        {/* Issuer */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
            Issuer
          </h4>
          <div className="divide-y">
            <Field label="Common Name (CN)" value={cert.issuer.common_name} />
            <Field label="Organization (O)" value={cert.issuer.organization} />
            <Field
              label="Organizational Unit (OU)"
              value={cert.issuer.organizational_unit}
            />
            <Field label="Country (C)" value={cert.issuer.country} />
          </div>
        </div>

        {/* Validity */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
            Validity Period
          </h4>
          <div className="divide-y">
            <Field label="Not Before" value={formatDate(cert.validity.not_before)} />
            <Field label="Not After" value={formatDate(cert.validity.not_after)} />
          </div>
        </div>

        {/* SANs */}
        {(hasDnsSans || hasIpSans || hasEmailSans) && (
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              Subject Alternative Names
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {cert.san.dns_names.map((name) => (
                <Badge key={`dns-${name}`} variant="outline">
                  DNS: {name}
                </Badge>
              ))}
              {cert.san.ip_addresses.map((ip) => (
                <Badge key={`ip-${ip}`} variant="outline">
                  IP: {ip}
                </Badge>
              ))}
              {cert.san.emails.map((email) => (
                <Badge key={`email-${email}`} variant="outline">
                  Email: {email}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Key Usage & Extended Key Usage */}
        {(cert.key_usage.length > 0 || cert.extended_key_usage.length > 0) && (
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              Key Usage
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {cert.key_usage.map((u) => (
                <Badge key={u} variant="secondary" className="text-xs">
                  {formatUsage(u)}
                </Badge>
              ))}
              {cert.extended_key_usage.map((u) => (
                <Badge key={u} variant="secondary" className="text-xs">
                  {u}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Technical Details */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
            Technical Details
          </h4>
          <div className="divide-y">
            <Field label="Version" value={cert.version} />
            <Field label="Serial Number" value={cert.serial_number} mono copyable />
            <Field
              label="Signature Algorithm"
              value={cert.signature_algorithm}
            />
            <Field
              label="Public Key"
              value={`${cert.public_key_algorithm.replace("_", " ")} ${cert.public_key_size} bit`}
            />
          </div>
        </div>

        {/* Fingerprints */}
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
            Fingerprints
          </h4>
          <div className="divide-y">
            <Field
              label="SHA-256"
              value={cert.fingerprint_sha256}
              mono
              copyable
            />
            <Field
              label="SHA-1"
              value={cert.fingerprint_sha1}
              mono
              copyable
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function CertificateManager() {
  const { data, isLoading, isError, refetch } = useCertificateInfo();
  const [showInstructions, setShowInstructions] = useState(false);

  const handleDownload = async () => {
    const token = localStorage.getItem("access_token");
    const res = await fetch("/api/v1/system/certificate/download", {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "mailcue-ca.crt";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">TLS Certificate</h2>
          <p className="text-sm text-muted-foreground">
            Download and install the CA certificate to trust MailCue connections.
          </p>
        </div>
        <Button onClick={handleDownload} disabled={isLoading || isError}>
          <Download className="mr-1.5 h-4 w-4" />
          Download CA Certificate
        </Button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : isError ? (
        <Card>
          <CardContent className="py-12 text-center">
            <CardDescription>
              Failed to load certificate information.
            </CardDescription>
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() => void refetch()}
            >
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : data ? (
        <>
          {/* Server Certificate */}
          <CertificateCard
            cert={data.server}
            title="Server Certificate"
            icon={
              <ShieldCheck className="h-5 w-5 text-muted-foreground" />
            }
          />

          {/* CA Certificate */}
          {data.ca && (
            <CertificateCard
              cert={data.ca}
              title="CA Certificate"
              icon={
                <ShieldAlert className="h-5 w-5 text-muted-foreground" />
              }
            />
          )}

          {/* Install instructions */}
          <Card>
            <button
              type="button"
              className="flex w-full items-center justify-between p-6 text-left"
              onClick={() => setShowInstructions(!showInstructions)}
            >
              <span className="text-base font-semibold leading-none tracking-tight">
                Installation Instructions
              </span>
              {showInstructions ? (
                <ChevronUp className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              )}
            </button>
            {showInstructions && (
              <CardContent className="space-y-4 border-t pt-4">
                <div>
                  <h4 className="text-sm font-semibold mb-1">macOS</h4>
                  <div className="rounded-md bg-muted p-3">
                    <code className="text-xs whitespace-pre-wrap">
                      {`sudo security add-trusted-cert -d -r trustRoot \\
  -k /Library/Keychains/System.keychain mailcue-ca.crt`}
                    </code>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Or double-click the file to open Keychain Access, then set
                    it to &quot;Always Trust&quot;.
                  </p>
                </div>

                <div>
                  <h4 className="text-sm font-semibold mb-1">
                    Linux (Debian/Ubuntu)
                  </h4>
                  <div className="rounded-md bg-muted p-3">
                    <code className="text-xs whitespace-pre-wrap">
                      {`sudo cp mailcue-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates`}
                    </code>
                  </div>
                </div>

                <div>
                  <h4 className="text-sm font-semibold mb-1">
                    Linux (RHEL/Fedora)
                  </h4>
                  <div className="rounded-md bg-muted p-3">
                    <code className="text-xs whitespace-pre-wrap">
                      {`sudo cp mailcue-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust`}
                    </code>
                  </div>
                </div>

                <div>
                  <h4 className="text-sm font-semibold mb-1">Windows</h4>
                  <div className="rounded-md bg-muted p-3">
                    <code className="text-xs whitespace-pre-wrap">
                      {`certutil -addstore -f "ROOT" mailcue-ca.crt`}
                    </code>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Run in an elevated Command Prompt, or double-click the file
                    and install to &quot;Trusted Root Certification
                    Authorities&quot;.
                  </p>
                </div>

                <div>
                  <h4 className="text-sm font-semibold mb-1">
                    Docker / CI Pipelines
                  </h4>
                  <div className="rounded-md bg-muted p-3">
                    <code className="text-xs whitespace-pre-wrap">
                      {`# In Dockerfile or CI script:
curl -o /usr/local/share/ca-certificates/mailcue-ca.crt \\
  http://<mailcue-host>/api/v1/system/certificate/download
update-ca-certificates`}
                    </code>
                  </div>
                </div>
              </CardContent>
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}

export { CertificateManager };
