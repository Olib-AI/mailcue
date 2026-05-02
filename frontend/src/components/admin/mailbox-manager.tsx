import { useState, useCallback } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import {
  Plus,
  Trash2,
  Loader2,
  Mail,
  AlertCircle,
  RefreshCw,
  Eraser,
  Pencil,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  useMailboxes,
  useCreateMailbox,
  useDeleteMailbox,
  usePurgeMailbox,
  useUpdateDisplayName,
} from "@/hooks/use-mailboxes";
import type { Mailbox } from "@/types/api";
import { formatEmailDate } from "@/lib/utils";

const createMailboxSchema = z.object({
  username: z
    .string()
    .min(1, "Username is required")
    .regex(
      /^[a-zA-Z0-9._-]+$/,
      "Username can only contain letters, numbers, dots, hyphens, and underscores"
    ),
  password: z.string().min(4, "Password must be at least 4 characters"),
  domain: z.string().optional(),
  display_name: z
    .string()
    .max(255, "Sender name must be 255 characters or fewer")
    .optional(),
});

type CreateMailboxValues = z.infer<typeof createMailboxSchema>;

function MailboxManager() {
  const { data, isLoading, isError, error, refetch } = useMailboxes();
  const createMailbox = useCreateMailbox();
  const deleteMailbox = useDeleteMailbox();
  const purgeMailbox = usePurgeMailbox();
  const updateDisplayName = useUpdateDisplayName();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [purgeTarget, setPurgeTarget] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<Mailbox | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<CreateMailboxValues>({
    resolver: zodResolver(createMailboxSchema),
    defaultValues: { username: "", password: "", domain: "", display_name: "" },
  });

  const onCreateSubmit = (values: CreateMailboxValues) => {
    createMailbox.mutate(
      {
        username: values.username,
        password: values.password,
        domain: values.domain || undefined,
        display_name: values.display_name?.trim() || undefined,
      },
      {
        onSuccess: (result) => {
          toast.success(`Mailbox created: ${result.address}`);
          reset();
          setCreateDialogOpen(false);
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to create mailbox"
          );
        },
      }
    );
  };

  const handleDelete = useCallback(() => {
    if (!deleteTarget) return;
    deleteMailbox.mutate(deleteTarget, {
      onSuccess: () => {
        toast.success(`Mailbox deleted: ${deleteTarget}`);
        setDeleteTarget(null);
      },
      onError: (err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to delete mailbox"
        );
      },
    });
  }, [deleteTarget, deleteMailbox]);

  const handlePurge = useCallback(() => {
    if (!purgeTarget) return;
    purgeMailbox.mutate(purgeTarget, {
      onSuccess: (result) => {
        toast.success(
          `Cleaned ${purgeTarget}: ${result.deleted} email${result.deleted !== 1 ? "s" : ""} removed`
        );
        setPurgeTarget(null);
      },
      onError: (err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to clean mailbox"
        );
      },
    });
  }, [purgeTarget, purgeMailbox]);

  const openRename = useCallback((mailbox: Mailbox) => {
    setRenameTarget(mailbox);
    setRenameValue(mailbox.display_name ?? "");
  }, []);

  const handleRename = useCallback(() => {
    if (!renameTarget) return;
    updateDisplayName.mutate(
      { address: renameTarget.address, display_name: renameValue.trim() },
      {
        onSuccess: () => {
          toast.success(`Sender name updated for ${renameTarget.address}`);
          setRenameTarget(null);
          setRenameValue("");
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to update sender name"
          );
        },
      }
    );
  }, [renameTarget, renameValue, updateDisplayName]);

  const mailboxes = data?.mailboxes ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Mailboxes</h2>
          <p className="text-sm text-muted-foreground">
            Manage email accounts for testing
          </p>
        </div>
        <Button onClick={() => setCreateDialogOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Create Mailbox
        </Button>
      </div>

      {/* Mailbox List */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-5 w-40" />
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-4 w-32" />
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
                : "Failed to load mailboxes"}
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
      ) : mailboxes.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Mail className="h-12 w-12 text-muted-foreground/50 mb-3" />
            <p className="text-sm font-medium text-muted-foreground">
              No mailboxes yet
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Create your first mailbox to start receiving test emails
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {mailboxes.map((mailbox) => (
            <Card key={mailbox.address}>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate">{mailbox.address}</div>
                    {mailbox.display_name ? (
                      <div className="text-xs font-normal text-muted-foreground truncate">
                        Sender name: {mailbox.display_name}
                      </div>
                    ) : (
                      <div className="text-xs font-normal text-muted-foreground/70 italic">
                        No sender name set
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-0.5 shrink-0">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-foreground"
                      onClick={() => openRename(mailbox)}
                      aria-label={`Edit sender name for ${mailbox.address}`}
                      title="Edit sender name"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-orange-600"
                      onClick={() => setPurgeTarget(mailbox.address)}
                      disabled={mailbox.email_count === 0}
                      aria-label={`Clean ${mailbox.address}`}
                      title="Delete all emails"
                    >
                      <Eraser className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-destructive"
                      onClick={() => setDeleteTarget(mailbox.address)}
                      aria-label={`Delete ${mailbox.address}`}
                      title="Delete mailbox"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-1 text-sm text-muted-foreground">
                  <div className="flex justify-between">
                    <span>Emails</span>
                    <span className="font-medium text-foreground">
                      {mailbox.email_count}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Unread</span>
                    <span className="font-medium text-foreground">
                      {mailbox.unread_count}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Created</span>
                    <span>{formatEmailDate(mailbox.created_at)}</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create Mailbox</DialogTitle>
            <DialogDescription>
              Create a new email account for testing. The full address will be
              generated from the username and domain.
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit(onCreateSubmit)} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="mb-username">Username (local part)</Label>
              <Input
                id="mb-username"
                placeholder="alice"
                autoFocus
                {...register("username")}
              />
              {errors.username && (
                <p className="text-xs text-destructive">
                  {errors.username.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="mb-password">Password</Label>
              <Input
                id="mb-password"
                type="password"
                placeholder="Account password"
                {...register("password")}
              />
              {errors.password && (
                <p className="text-xs text-destructive">
                  {errors.password.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="mb-domain">
                Domain{" "}
                <span className="text-muted-foreground font-normal">
                  (optional)
                </span>
              </Label>
              <Input
                id="mb-domain"
                placeholder="mailcue.local"
                {...register("domain")}
              />
              {errors.domain && (
                <p className="text-xs text-destructive">
                  {errors.domain.message}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="mb-display-name">
                Sender name{" "}
                <span className="text-muted-foreground font-normal">
                  (optional)
                </span>
              </Label>
              <Input
                id="mb-display-name"
                placeholder="Akram Hasan"
                autoComplete="off"
                {...register("display_name")}
              />
              <p className="text-xs text-muted-foreground">
                Shown as the &quot;From&quot; display name on outbound mail.
                Leave blank to use just the address.
              </p>
              {errors.display_name && (
                <p className="text-xs text-destructive">
                  {errors.display_name.message}
                </p>
              )}
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  reset();
                  setCreateDialogOpen(false);
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createMailbox.isPending}>
                {createMailbox.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Create Mailbox
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
            <DialogTitle>Delete Mailbox</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete{" "}
              <strong>{deleteTarget}</strong>? This action cannot be undone.
              All emails in this mailbox will be permanently deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMailbox.isPending}
            >
              {deleteMailbox.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Rename (display name) Dialog */}
      <Dialog
        open={renameTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRenameTarget(null);
            setRenameValue("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit sender name</DialogTitle>
            <DialogDescription>
              Set the display name shown alongside{" "}
              <strong>{renameTarget?.address}</strong> when this mailbox sends
              mail. Leave empty to send with just the address.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5 py-2">
            <Label htmlFor="mb-rename-display-name">Sender name</Label>
            <Input
              id="mb-rename-display-name"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              placeholder="Akram Hasan"
              autoFocus
              maxLength={255}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleRename();
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setRenameTarget(null);
                setRenameValue("");
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={handleRename}
              disabled={updateDisplayName.isPending}
            >
              {updateDisplayName.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Purge Confirmation Dialog */}
      <Dialog
        open={purgeTarget !== null}
        onOpenChange={(open) => {
          if (!open) setPurgeTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Clean Mailbox</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete all emails from{" "}
              <strong>{purgeTarget}</strong>? This will permanently remove
              every email in all folders. The mailbox itself will be kept.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPurgeTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handlePurge}
              disabled={purgeMailbox.isPending}
            >
              {purgeMailbox.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Delete All Emails
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export { MailboxManager };
