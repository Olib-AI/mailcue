import { useState, useCallback } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import {
  Plus,
  Trash2,
  Loader2,
  KeyRound,
  AlertCircle,
  RefreshCw,
  Upload,
  Download,
  Copy,
  Globe,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  useGpgKeys,
  useGenerateGpgKey,
  useImportGpgKey,
  useDeleteGpgKey,
  useExportGpgKey,
  usePublishGpgKey,
} from "@/hooks/use-gpg";
import { useMailboxes } from "@/hooks/use-mailboxes";
import { useDomains } from "@/hooks/use-domains";
import { formatEmailDate } from "@/lib/utils";

// --- Generate Key Schema ---

const generateKeySchema = z.object({
  mailbox_address: z.string().min(1, "Select a mailbox"),
  name: z.string().optional(),
  algorithm: z.enum(["RSA", "ECC"]),
  key_length: z.coerce.number().optional(),
  expire: z.string().optional(),
});

type GenerateKeyValues = z.infer<typeof generateKeySchema>;
type GenerateKeyFormValues = z.input<typeof generateKeySchema>;

// --- Import Key Schema ---

const importKeySchema = z.object({
  armored_key: z.string().min(1, "Paste an armored GPG key"),
  mailbox_address: z.string().optional(),
});

type ImportKeyValues = z.infer<typeof importKeySchema>;

// --- Component ---

function GpgKeyManager() {
  const { data, isLoading, isError, error, refetch } = useGpgKeys();
  const { data: mailboxData } = useMailboxes();
  const { data: domainData } = useDomains();
  const generateKey = useGenerateGpgKey();
  const importKey = useImportGpgKey();
  const deleteKey = useDeleteGpgKey();
  const exportKey = useExportGpgKey();
  const publishKey = usePublishGpgKey();

  const [generateDialogOpen, setGenerateDialogOpen] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const mailboxes = mailboxData?.mailboxes ?? [];
  const keys = data?.keys ?? [];

  // Build set of local domains (managed domains + mailbox domains)
  const localDomains = new Set<string>();
  for (const d of domainData?.domains ?? []) {
    localDomains.add(d.name.toLowerCase());
  }
  for (const mb of mailboxes) {
    localDomains.add(mb.domain.toLowerCase());
  }

  const isLocalDomain = (address: string) => {
    const domain = address.split("@")[1]?.toLowerCase();
    return domain ? localDomains.has(domain) : true;
  };

  // --- Generate Form ---

  const generateForm = useForm<
    GenerateKeyFormValues,
    unknown,
    GenerateKeyValues
  >({
    resolver: zodResolver(generateKeySchema),
    defaultValues: {
      mailbox_address: "",
      name: "",
      algorithm: "RSA",
      key_length: 2048,
      expire: "",
    },
  });

  const onGenerateSubmit = (values: GenerateKeyValues) => {
    generateKey.mutate(
      {
        mailbox_address: values.mailbox_address,
        name: values.name || undefined,
        algorithm: values.algorithm,
        key_length: values.key_length || undefined,
        expire: values.expire || undefined,
      },
      {
        onSuccess: (result) => {
          toast.success(`GPG key generated for ${result.mailbox_address}`);
          generateForm.reset();
          setGenerateDialogOpen(false);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to generate key"
          );
        },
      }
    );
  };

  // --- Import Form ---

  const importForm = useForm<ImportKeyValues>({
    resolver: zodResolver(importKeySchema),
    defaultValues: {
      armored_key: "",
      mailbox_address: "",
    },
  });

  const onImportSubmit = (values: ImportKeyValues) => {
    importKey.mutate(
      {
        armored_key: values.armored_key,
        mailbox_address: values.mailbox_address || undefined,
      },
      {
        onSuccess: (result) => {
          toast.success(`GPG key imported for ${result.mailbox_address}`);
          importForm.reset();
          setImportDialogOpen(false);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to import key"
          );
        },
      }
    );
  };

  // --- Delete ---

  const handleDelete = useCallback(() => {
    if (!deleteTarget) return;
    deleteKey.mutate(deleteTarget, {
      onSuccess: () => {
        toast.success(`GPG key deleted for ${deleteTarget}`);
        setDeleteTarget(null);
      },
      onError: (err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to delete key"
        );
      },
    });
  }, [deleteTarget, deleteKey]);

  // --- Export ---

  const handleExport = useCallback(
    (address: string) => {
      exportKey.mutate(address, {
        onSuccess: (result) => {
          void navigator.clipboard.writeText(result.public_key).then(() => {
            toast.success("Public key copied to clipboard");
          });
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to export key"
          );
        },
      });
    },
    [exportKey]
  );

  const handleDownload = useCallback(
    (address: string) => {
      exportKey.mutate(address, {
        onSuccess: (result) => {
          const blob = new Blob([result.public_key], {
            type: "application/pgp-keys",
          });
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = `${result.fingerprint}.asc`;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          URL.revokeObjectURL(url);
          toast.success("Key downloaded");
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to download key"
          );
        },
      });
    },
    [exportKey]
  );

  const handlePublish = useCallback(
    (address: string) => {
      publishKey.mutate(address, {
        onSuccess: (result) => {
          toast.success(result.message);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to publish key"
          );
        },
      });
    },
    [publishKey]
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">GPG Keys</h2>
          <p className="text-sm text-muted-foreground">
            Manage GPG keys for signing and encrypting emails
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => setImportDialogOpen(true)}
          >
            <Upload className="mr-2 h-4 w-4" />
            Import Key
          </Button>
          <Button onClick={() => setGenerateDialogOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Generate Key
          </Button>
        </div>
      </div>

      {/* Key List */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-5 w-40" />
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-4 w-24" />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : isError ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-8">
            <AlertCircle className="h-10 w-10 text-destructive mb-3" />
            <p className="text-sm text-destructive mb-3">
              {error instanceof Error
                ? error.message
                : "Failed to load GPG keys"}
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
      ) : keys.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <KeyRound className="h-12 w-12 text-muted-foreground/50 mb-3" />
            <p className="text-sm font-medium text-muted-foreground">
              No GPG keys yet
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Generate or import a GPG key to sign and encrypt emails
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {keys.map((key) => (
            <Card key={key.id}>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center justify-between">
                  <span className="truncate">{key.mailbox_address}</span>
                  <div className="flex gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-foreground"
                      onClick={() => handleExport(key.mailbox_address)}
                      title="Copy public key to clipboard"
                      aria-label={`Copy public key for ${key.mailbox_address}`}
                    >
                      <Copy className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-foreground"
                      onClick={() => handleDownload(key.mailbox_address)}
                      title="Download .asc file"
                      aria-label={`Download key for ${key.mailbox_address}`}
                    >
                      <Download className="h-4 w-4" />
                    </Button>
                    {!isLocalDomain(key.mailbox_address) && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-foreground"
                        onClick={() => handlePublish(key.mailbox_address)}
                        disabled={publishKey.isPending}
                        title="Publish to keys.openpgp.org"
                        aria-label={`Publish key for ${key.mailbox_address} to keyserver`}
                      >
                        {publishKey.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Globe className="h-4 w-4" />
                        )}
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-destructive"
                      onClick={() => setDeleteTarget(key.mailbox_address)}
                      aria-label={`Delete key for ${key.mailbox_address}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <div className="flex gap-1.5">
                    {key.is_private ? (
                      <Badge variant="default" className="text-xs">
                        Private
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="text-xs">
                        Public
                      </Badge>
                    )}
                    {key.algorithm && (
                      <Badge variant="outline" className="text-xs">
                        {key.algorithm}
                        {key.key_length ? ` ${key.key_length}` : ""}
                      </Badge>
                    )}
                  </div>
                  <div className="space-y-1 text-sm text-muted-foreground">
                    <div>
                      <span className="text-xs">Fingerprint</span>
                      <p
                        className="font-mono text-xs text-foreground truncate"
                        title={key.fingerprint}
                      >
                        {key.fingerprint}
                      </p>
                    </div>
                    {key.uid_name && (
                      <div className="flex justify-between">
                        <span>Name</span>
                        <span className="text-foreground truncate ml-2">
                          {key.uid_name}
                        </span>
                      </div>
                    )}
                    <div className="flex justify-between">
                      <span>Created</span>
                      <span>{formatEmailDate(key.created_at)}</span>
                    </div>
                    {key.expires_at && (
                      <div className="flex justify-between">
                        <span>Expires</span>
                        <span>{formatEmailDate(key.expires_at)}</span>
                      </div>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Generate Key Dialog */}
      <Dialog open={generateDialogOpen} onOpenChange={setGenerateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Generate GPG Key</DialogTitle>
            <DialogDescription>
              Generate a new GPG key pair for a mailbox. The private key will be
              stored on the server for signing outgoing emails.
            </DialogDescription>
          </DialogHeader>

          <form
            onSubmit={generateForm.handleSubmit(onGenerateSubmit)}
            className="space-y-4"
          >
            <div className="space-y-1.5">
              <Label htmlFor="gen-mailbox">Mailbox</Label>
              <Select
                id="gen-mailbox"
                {...generateForm.register("mailbox_address")}
              >
                <option value="">Select mailbox...</option>
                {mailboxes.map((mb) => (
                  <option key={mb.address} value={mb.address}>
                    {mb.address}
                  </option>
                ))}
              </Select>
              {generateForm.formState.errors.mailbox_address && (
                <p className="text-xs text-destructive">
                  {generateForm.formState.errors.mailbox_address.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="gen-name">
                Name{" "}
                <span className="text-muted-foreground font-normal">
                  (optional)
                </span>
              </Label>
              <Input
                id="gen-name"
                placeholder="Key owner name"
                {...generateForm.register("name")}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="gen-algorithm">Algorithm</Label>
              <Select
                id="gen-algorithm"
                {...generateForm.register("algorithm")}
              >
                <option value="RSA">RSA</option>
                <option value="ECC">ECC</option>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="gen-key-length">Key Length</Label>
              <Select
                id="gen-key-length"
                {...generateForm.register("key_length")}
              >
                <option value="2048">2048</option>
                <option value="3072">3072</option>
                <option value="4096">4096</option>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="gen-expire">
                Expiration{" "}
                <span className="text-muted-foreground font-normal">
                  (optional, e.g. 1y, 6m, 90d)
                </span>
              </Label>
              <Input
                id="gen-expire"
                placeholder="Never"
                {...generateForm.register("expire")}
              />
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  generateForm.reset();
                  setGenerateDialogOpen(false);
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={generateKey.isPending}>
                {generateKey.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Generate Key
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Import Key Dialog */}
      <Dialog open={importDialogOpen} onOpenChange={setImportDialogOpen}>
        <DialogContent className="sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle>Import GPG Key</DialogTitle>
            <DialogDescription>
              Paste an ASCII-armored GPG public or private key to import it.
            </DialogDescription>
          </DialogHeader>

          <form
            onSubmit={importForm.handleSubmit(onImportSubmit)}
            className="space-y-4"
          >
            <div className="space-y-1.5">
              <Label htmlFor="import-key">Armored Key</Label>
              <Textarea
                id="import-key"
                placeholder="-----BEGIN PGP PUBLIC KEY BLOCK-----&#10;...&#10;-----END PGP PUBLIC KEY BLOCK-----"
                rows={10}
                className="font-mono text-xs"
                {...importForm.register("armored_key")}
              />
              {importForm.formState.errors.armored_key && (
                <p className="text-xs text-destructive">
                  {importForm.formState.errors.armored_key.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="import-mailbox">
                Mailbox Override{" "}
                <span className="text-muted-foreground font-normal">
                  (optional)
                </span>
              </Label>
              <Select
                id="import-mailbox"
                {...importForm.register("mailbox_address")}
              >
                <option value="">Auto-detect from key UID</option>
                {mailboxes.map((mb) => (
                  <option key={mb.address} value={mb.address}>
                    {mb.address}
                  </option>
                ))}
              </Select>
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  importForm.reset();
                  setImportDialogOpen(false);
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={importKey.isPending}>
                {importKey.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Import Key
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete GPG Key</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete the GPG key for{" "}
              <strong>{deleteTarget}</strong>? This action cannot be undone.
              Signed emails will no longer be verifiable with this key.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteKey.isPending}
            >
              {deleteKey.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export { GpgKeyManager };
