import { useState, useCallback } from "react";
import { toast } from "sonner";
import {
  Plus,
  Pencil,
  Trash2,
  Loader2,
  AlertCircle,
  RefreshCw,
  ArrowRightLeft,
  Globe,
  Mail,
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
  useForwardingRules,
  useDeleteForwardingRule,
  useUpdateForwardingRule,
} from "@/hooks/use-forwarding-rules";
import { RuleDialog } from "@/components/forwarding/rule-dialog";
import { formatEmailDate } from "@/lib/utils";
import type { ForwardingRule } from "@/types/api";

function RulesManager() {
  const { data, isLoading, isError, error, refetch } = useForwardingRules();
  const deleteRule = useDeleteForwardingRule();
  const updateRule = useUpdateForwardingRule();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<ForwardingRule | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ForwardingRule | null>(null);

  const rules = data?.rules ?? [];

  const handleCreate = () => {
    setEditingRule(null);
    setDialogOpen(true);
  };

  const handleEdit = (rule: ForwardingRule) => {
    setEditingRule(rule);
    setDialogOpen(true);
  };

  const handleToggleEnabled = (rule: ForwardingRule) => {
    updateRule.mutate(
      { id: rule.id, data: { enabled: !rule.enabled } },
      {
        onSuccess: () => {
          toast.success(
            `Rule "${rule.name}" ${rule.enabled ? "disabled" : "enabled"}`
          );
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to update rule"
          );
        },
      }
    );
  };

  const handleDelete = useCallback(() => {
    if (!deleteTarget) return;
    deleteRule.mutate(deleteTarget.id, {
      onSuccess: () => {
        toast.success(`Rule "${deleteTarget.name}" deleted`);
        setDeleteTarget(null);
      },
      onError: (err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to delete rule"
        );
      },
    });
  }, [deleteTarget, deleteRule]);

  const getActionLabel = (rule: ForwardingRule) => {
    if (rule.action_type === "smtp_forward") {
      return rule.action_config.to_address ?? "SMTP Forward";
    }
    return rule.action_config.url ?? "Webhook";
  };

  const getPatternSummary = (rule: ForwardingRule): string => {
    const parts: string[] = [];
    if (rule.match_from) parts.push(`from: ${rule.match_from}`);
    if (rule.match_to) parts.push(`to: ${rule.match_to}`);
    if (rule.match_subject) parts.push(`subject: ${rule.match_subject}`);
    if (rule.match_mailbox) parts.push(`mailbox: ${rule.match_mailbox}`);
    return parts.length > 0 ? parts.join(", ") : "Match all emails";
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            Forwarding Rules
          </h2>
          <p className="text-sm text-muted-foreground">
            Automatically forward emails via SMTP or webhook based on pattern
            matching
          </p>
        </div>
        <Button onClick={handleCreate}>
          <Plus className="mr-2 h-4 w-4" />
          Create Rule
        </Button>
      </div>

      {/* Rules List */}
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
                : "Failed to load forwarding rules"}
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
      ) : rules.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <ArrowRightLeft className="h-12 w-12 text-muted-foreground/50 mb-3" />
            <p className="text-sm font-medium text-muted-foreground">
              No forwarding rules yet
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Create your first rule to start forwarding emails automatically
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {rules.map((rule) => (
            <Card
              key={rule.id}
              className={!rule.enabled ? "opacity-60" : undefined}
            >
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm">{rule.name}</span>
                      <Badge
                        variant={rule.enabled ? "default" : "secondary"}
                        className="text-[10px] px-1.5 py-0"
                      >
                        {rule.enabled ? "Enabled" : "Disabled"}
                      </Badge>
                      <Badge
                        variant="outline"
                        className="text-[10px] px-1.5 py-0 gap-1"
                      >
                        {rule.action_type === "smtp_forward" ? (
                          <Mail className="h-3 w-3" />
                        ) : (
                          <Globe className="h-3 w-3" />
                        )}
                        {rule.action_type === "smtp_forward"
                          ? "SMTP"
                          : "Webhook"}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground truncate">
                      {getPatternSummary(rule)}
                    </p>
                    <p className="text-xs text-muted-foreground truncate">
                      <span className="font-medium">Action:</span>{" "}
                      {getActionLabel(rule)}
                    </p>
                    <p className="text-[10px] text-muted-foreground/60">
                      Created {formatEmailDate(rule.created_at)}
                      {rule.updated_at !== rule.created_at && (
                        <> &middot; Updated {formatEmailDate(rule.updated_at)}</>
                      )}
                    </p>
                  </div>

                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleToggleEnabled(rule)}
                      className="text-xs h-7 px-2"
                    >
                      {rule.enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-foreground"
                      onClick={() => handleEdit(rule)}
                      aria-label={`Edit ${rule.name}`}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-destructive"
                      onClick={() => setDeleteTarget(rule)}
                      aria-label={`Delete ${rule.name}`}
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
      <RuleDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        rule={editingRule}
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
            <DialogTitle>Delete Forwarding Rule</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete the rule{" "}
              <strong>{deleteTarget?.name}</strong>? This action cannot be
              undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteRule.isPending}
            >
              {deleteRule.isPending && (
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

export { RulesManager };
