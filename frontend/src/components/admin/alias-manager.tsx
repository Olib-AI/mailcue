import { useState, useCallback } from "react";
import { toast } from "sonner";
import {
  Plus,
  Pencil,
  Trash2,
  Loader2,
  AlertCircle,
  RefreshCw,
  AtSign,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  useAliases,
  useDeleteAlias,
  useUpdateAlias,
} from "@/hooks/use-aliases";
import { AliasDialog } from "@/components/admin/alias-dialog";
import { formatEmailDate } from "@/lib/utils";
import type { Alias } from "@/types/api";

function AliasManager() {
  const { data, isLoading, isError, error, refetch } = useAliases();
  const deleteAlias = useDeleteAlias();
  const updateAlias = useUpdateAlias();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingAlias, setEditingAlias] = useState<Alias | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Alias | null>(null);

  const aliases = data?.aliases ?? [];

  const handleCreate = () => {
    setEditingAlias(null);
    setDialogOpen(true);
  };

  const handleEdit = (alias: Alias) => {
    setEditingAlias(alias);
    setDialogOpen(true);
  };

  const handleToggleEnabled = (alias: Alias) => {
    updateAlias.mutate(
      { id: alias.id, data: { enabled: !alias.enabled } },
      {
        onSuccess: () => {
          toast.success(
            `Alias "${alias.source_address}" ${alias.enabled ? "disabled" : "enabled"}`
          );
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to update alias"
          );
        },
      }
    );
  };

  const handleDelete = useCallback(() => {
    if (!deleteTarget) return;
    deleteAlias.mutate(deleteTarget.id, {
      onSuccess: () => {
        toast.success(`Alias "${deleteTarget.source_address}" deleted`);
        setDeleteTarget(null);
      },
      onError: (err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to delete alias"
        );
      },
    });
  }, [deleteTarget, deleteAlias]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            Email Aliases
          </h2>
          <p className="text-sm text-muted-foreground">
            Route incoming email from one address to another mailbox
          </p>
        </div>
        <Button onClick={handleCreate}>
          <Plus className="mr-2 h-4 w-4" />
          Create Alias
        </Button>
      </div>

      {/* Aliases List */}
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Card key={i}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div className="space-y-2 flex-1">
                    <Skeleton className="h-5 w-48" />
                    <Skeleton className="h-4 w-72" />
                  </div>
                  <Skeleton className="h-8 w-20" />
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
                : "Failed to load aliases"}
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
      ) : aliases.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <AtSign className="h-12 w-12 text-muted-foreground/50 mb-3" />
            <p className="text-sm font-medium text-muted-foreground">
              No email aliases yet
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Create your first alias to start routing emails
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {aliases.map((alias) => (
            <Card
              key={alias.id}
              className={!alias.enabled ? "opacity-60" : undefined}
            >
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm font-mono">
                        {alias.source_address}
                      </span>
                      <span className="text-muted-foreground text-sm">&rarr;</span>
                      <span className="text-sm font-mono">
                        {alias.destination_address}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge
                        variant={alias.enabled ? "default" : "secondary"}
                        className="text-[10px] px-1.5 py-0"
                      >
                        {alias.enabled ? "Enabled" : "Disabled"}
                      </Badge>
                      {alias.is_catch_all && (
                        <Badge
                          variant="outline"
                          className="text-[10px] px-1.5 py-0"
                        >
                          Catch-all
                        </Badge>
                      )}
                      <span className="text-xs text-muted-foreground">
                        {alias.domain}
                      </span>
                    </div>
                    <p className="text-[10px] text-muted-foreground/60">
                      Created {formatEmailDate(alias.created_at)}
                      {alias.updated_at !== alias.created_at && (
                        <> &middot; Updated {formatEmailDate(alias.updated_at)}</>
                      )}
                    </p>
                  </div>

                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleToggleEnabled(alias)}
                      className="text-xs h-7 px-2"
                    >
                      {alias.enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-foreground"
                      onClick={() => handleEdit(alias)}
                      aria-label={`Edit ${alias.source_address}`}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-destructive"
                      onClick={() => setDeleteTarget(alias)}
                      aria-label={`Delete ${alias.source_address}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create/Edit Dialog */}
      <AliasDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        alias={editingAlias}
      />

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Alias</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete the alias{" "}
              <strong>{deleteTarget?.source_address}</strong>? This action cannot
              be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteAlias.isPending}
            >
              {deleteAlias.isPending && (
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

export { AliasManager };
