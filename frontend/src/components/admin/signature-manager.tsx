import { useEffect, useMemo, useState } from "react";
import { Loader2, PenLine, Eye } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useMailboxes, useUpdateSignature } from "@/hooks/use-mailboxes";
import type { Mailbox } from "@/types/api";

function SignatureManager() {
  const { data: mailboxData, isLoading: mailboxesLoading } = useMailboxes();
  const updateSignature = useUpdateSignature();
  const mailboxes = useMemo(
    () => mailboxData?.mailboxes ?? [],
    [mailboxData?.mailboxes]
  );

  const [selectedAddress, setSelectedAddress] = useState("");
  const [signature, setSignature] = useState("");
  const [dirty, setDirty] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  // Select the first mailbox automatically when data loads
  useEffect(() => {
    if (mailboxes.length > 0 && !selectedAddress) {
      setSelectedAddress(mailboxes[0]?.address ?? "");
    }
  }, [mailboxes, selectedAddress]);

  // Sync local signature state when the selected mailbox changes
  useEffect(() => {
    const mailbox = mailboxes.find(
      (mb: Mailbox) => mb.address === selectedAddress
    );
    setSignature(mailbox?.signature ?? "");
    setDirty(false);
    setShowPreview(false);
  }, [selectedAddress, mailboxes]);

  const handleSave = () => {
    if (!selectedAddress) return;
    updateSignature.mutate(
      { address: selectedAddress, signature },
      {
        onSuccess: () => {
          toast.success("Signature saved");
          setDirty(false);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to save signature"
          );
        },
      }
    );
  };

  const previewHtml = signature
    ? `<br><br>--<br>${signature.replace(/\n/g, "<br>")}`
    : "";

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">
          Email Signatures
        </h2>
        <p className="text-sm text-muted-foreground">
          Configure a signature for each mailbox. It will be appended
          automatically when composing new emails.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <PenLine className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">Mailbox Signature</CardTitle>
          </div>
          <CardDescription>
            Select a mailbox and edit its signature below.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {mailboxesLoading ? (
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          ) : mailboxes.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No mailboxes available. Create a mailbox first.
            </p>
          ) : (
            <>
              {/* Mailbox selector */}
              <div className="space-y-1.5">
                <Label htmlFor="sig-mailbox">Mailbox</Label>
                <Select
                  id="sig-mailbox"
                  value={selectedAddress}
                  onChange={(e) => setSelectedAddress(e.target.value)}
                  className="max-w-sm"
                >
                  {mailboxes.map((mb: Mailbox) => (
                    <option key={mb.address} value={mb.address}>
                      {mb.display_name
                        ? `${mb.display_name} <${mb.address}>`
                        : mb.address}
                    </option>
                  ))}
                </Select>
              </div>

              {/* Signature editor */}
              <div className="space-y-1.5">
                <Label htmlFor="sig-body">Signature</Label>
                <Textarea
                  id="sig-body"
                  value={signature}
                  onChange={(e) => {
                    setSignature(e.target.value);
                    const mailbox = mailboxes.find(
                      (mb: Mailbox) => mb.address === selectedAddress
                    );
                    setDirty(e.target.value !== (mailbox?.signature ?? ""));
                  }}
                  placeholder="Enter your email signature (plain text)"
                  rows={6}
                  className="text-sm"
                />
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2">
                <Button
                  onClick={handleSave}
                  disabled={!dirty || updateSignature.isPending}
                  size="sm"
                >
                  {updateSignature.isPending && (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  )}
                  Save Signature
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setShowPreview((v) => !v)}
                >
                  <Eye className="mr-1.5 h-4 w-4" />
                  {showPreview ? "Hide Preview" : "Preview"}
                </Button>
              </div>

              {/* Preview */}
              {showPreview && (
                <div className="rounded-md border p-4 space-y-1">
                  <p className="text-xs font-medium text-muted-foreground mb-2">
                    Preview (how it will appear in emails)
                  </p>
                  {signature ? (
                    <div
                      className="text-sm prose prose-sm max-w-none dark:prose-invert"
                      dangerouslySetInnerHTML={{ __html: previewHtml }}
                    />
                  ) : (
                    <p className="text-sm text-muted-foreground italic">
                      No signature set
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export { SignatureManager };
