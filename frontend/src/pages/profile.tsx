import { useState, useCallback } from "react";
import {
  KeyRound,
  ShieldCheck,
  ShieldOff,
  User,
  Plus,
  Trash2,
  Loader2,
  Copy,
  Key,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
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
import { useAuth } from "@/hooks/use-auth";
import { useMailboxes, useUpdateDisplayName } from "@/hooks/use-mailboxes";
import {
  useApiKeys,
  useApiKeyScopes,
  useCreateApiKey,
  useRevokeApiKey,
} from "@/hooks/use-api-keys";
import { ChangePasswordDialog } from "@/components/auth/change-password-dialog";
import { TOTPSetupDialog } from "@/components/auth/totp-setup-dialog";
import { TOTPDisableDialog } from "@/components/auth/totp-disable-dialog";
import { cn, formatEmailDate } from "@/lib/utils";
import type { ApiKeyScope, CreateAPIKeyRequest } from "@/types/api";

type AccessMode = "full" | "custom";

function ProfilePage() {
  const { user, refreshUser } = useAuth();
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);
  const [totpSetupOpen, setTotpSetupOpen] = useState(false);
  const [totpDisableOpen, setTotpDisableOpen] = useState(false);

  // API Keys
  const { data: apiKeys, isLoading: keysLoading } = useApiKeys();
  const { data: scopeCatalog } = useApiKeyScopes();
  const createKey = useCreateApiKey();
  const revokeKey = useRevokeApiKey();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [createdKeyValue, setCreatedKeyValue] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<{ id: string; name: string } | null>(null);

  // API key permissions
  const [accessMode, setAccessMode] = useState<AccessMode>("full");
  const [selectedScopes, setSelectedScopes] = useState<Set<string>>(new Set());
  const [restrictMailboxes, setRestrictMailboxes] = useState(false);
  const [selectedMailboxes, setSelectedMailboxes] = useState<Set<string>>(
    new Set()
  );

  // Display name
  const { data: mailboxData } = useMailboxes();
  const updateDisplayName = useUpdateDisplayName();
  const userMailbox = mailboxData?.mailboxes?.find(
    (mb) => mb.address === user?.email
  );
  const mailboxes = mailboxData?.mailboxes ?? [];

  // Scopes available to this user, grouped in the order returned by the catalog.
  const scopeGroups = (() => {
    const visible = (scopeCatalog?.scopes ?? []).filter(
      (s) => user?.is_admin || !s.admin_only
    );
    const groups: { group: string; scopes: ApiKeyScope[] }[] = [];
    for (const scope of visible) {
      let entry = groups.find((g) => g.group === scope.group);
      if (!entry) {
        entry = { group: scope.group, scopes: [] };
        groups.push(entry);
      }
      entry.scopes.push(scope);
    }
    return groups;
  })();

  const toggleScope = (value: string) => {
    setSelectedScopes((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  };

  const toggleMailbox = (address: string) => {
    setSelectedMailboxes((prev) => {
      const next = new Set(prev);
      if (next.has(address)) next.delete(address);
      else next.add(address);
      return next;
    });
  };

  const [displayName, setDisplayName] = useState("");
  const [displayNameDirty, setDisplayNameDirty] = useState(false);

  // Sync display name from mailbox data
  const currentDisplayName = userMailbox?.display_name ?? "";
  if (!displayNameDirty && displayName !== currentDisplayName && currentDisplayName) {
    setDisplayName(currentDisplayName);
  }

  const handleSaveDisplayName = () => {
    if (!userMailbox) return;
    updateDisplayName.mutate(
      { address: userMailbox.address, display_name: displayName },
      {
        onSuccess: () => {
          toast.success("Display name updated");
          setDisplayNameDirty(false);
        },
        onError: () => toast.error("Failed to update display name"),
      }
    );
  };

  const customWithNoScopes =
    accessMode === "custom" && selectedScopes.size === 0;

  const handleCreateKey = () => {
    if (!newKeyName.trim()) return;
    if (customWithNoScopes) return;

    const payload: CreateAPIKeyRequest = { name: newKeyName.trim() };
    if (accessMode === "custom") {
      payload.scopes = Array.from(selectedScopes);
    }
    if (restrictMailboxes && selectedMailboxes.size > 0) {
      payload.allowed_mailboxes = Array.from(selectedMailboxes);
    }

    createKey.mutate(payload, {
      onSuccess: (result) => {
        setCreatedKeyValue(result.key);
        setNewKeyName("");
      },
      onError: (err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to create API key"
        );
      },
    });
  };

  const handleCloseCreateDialog = () => {
    setCreateDialogOpen(false);
    setCreatedKeyValue(null);
    setNewKeyName("");
    setAccessMode("full");
    setSelectedScopes(new Set());
    setRestrictMailboxes(false);
    setSelectedMailboxes(new Set());
  };

  const handleCopyKey = useCallback((key: string) => {
    void navigator.clipboard.writeText(key).then(() => {
      toast.success("API key copied to clipboard");
    });
  }, []);

  const handleRevoke = () => {
    if (!revokeTarget) return;
    revokeKey.mutate(revokeTarget.id, {
      onSuccess: () => {
        toast.success(`API key "${revokeTarget.name}" removed`);
        setRevokeTarget(null);
      },
      onError: (err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to remove API key"
        );
      },
    });
  };

  const handleTotpChanged = () => {
    void refreshUser();
  };

  if (!user) return null;

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-6">
      <h1 className="text-2xl font-bold">Profile</h1>

      {/* Account Info */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <User className="h-5 w-5" />
            Account Information
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex justify-between">
            <span className="text-sm text-muted-foreground">Username</span>
            <span className="text-sm font-medium">{user.username}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-muted-foreground">Email</span>
            <span className="text-sm font-medium">{user.email}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-muted-foreground">Role</span>
            <Badge variant={user.is_admin ? "default" : "secondary"}>
              {user.is_admin ? "Admin" : "User"}
            </Badge>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-muted-foreground">Mailbox Quota</span>
            <span className="text-sm font-medium">
              {mailboxData?.mailboxes.length ?? 0} / {user.max_mailboxes} mailboxes
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Display Name */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <User className="h-5 w-5" />
            Display Name
          </CardTitle>
          <CardDescription>
            This name appears in the &quot;From&quot; field when you send emails.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Input
              value={displayName}
              onChange={(e) => {
                setDisplayName(e.target.value);
                setDisplayNameDirty(true);
              }}
              placeholder="Your full name"
            />
            <Button
              onClick={handleSaveDisplayName}
              disabled={!displayNameDirty || updateDisplayName.isPending}
            >
              {updateDisplayName.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                "Save"
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Password */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="h-5 w-5" />
            Password
          </CardTitle>
          <CardDescription>
            Change your account password.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="outline"
            onClick={() => setChangePasswordOpen(true)}
          >
            Change Password
          </Button>
        </CardContent>
      </Card>

      {/* Two-Factor Authentication */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {user.totp_enabled ? (
              <ShieldCheck className="h-5 w-5 text-green-600" />
            ) : (
              <ShieldOff className="h-5 w-5 text-muted-foreground" />
            )}
            Two-Factor Authentication
            {user.totp_enabled ? (
              <Badge className="ml-2 bg-green-600 text-white">Enabled</Badge>
            ) : (
              <Badge variant="secondary" className="ml-2">
                Disabled
              </Badge>
            )}
          </CardTitle>
          <CardDescription>
            {user.totp_enabled
              ? "Your account is protected with TOTP-based two-factor authentication."
              : "Add an extra layer of security to your account with an authenticator app."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {user.totp_enabled ? (
            <Button
              variant="destructive"
              onClick={() => setTotpDisableOpen(true)}
            >
              Disable 2FA
            </Button>
          ) : (
            <Button onClick={() => setTotpSetupOpen(true)}>Enable 2FA</Button>
          )}
        </CardContent>
      </Card>

      {/* API Keys */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Key className="h-5 w-5" />
              API Keys
            </CardTitle>
            <Button
              size="sm"
              onClick={() => setCreateDialogOpen(true)}
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Create Key
            </Button>
          </div>
          <CardDescription>
            Create API keys for programmatic access. Authenticate with the{" "}
            <code className="text-xs bg-muted px-1 py-0.5 rounded">X-API-Key</code> header.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {keysLoading ? (
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          ) : !apiKeys || apiKeys.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No API keys created yet.
            </p>
          ) : (
            <div className="space-y-2">
              {apiKeys.map((k) => (
                <div
                  key={k.id}
                  className="flex items-start justify-between gap-2 rounded-md border p-3"
                >
                  <div className="min-w-0 space-y-1">
                    <span className="text-sm font-medium">{k.name}</span>
                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      <span>
                        Prefix: <code className="bg-muted px-1 rounded">{k.prefix}...</code>
                      </span>
                      <span>Created {formatEmailDate(k.created_at)}</span>
                      {k.last_used_at && (
                        <span>Last used {formatEmailDate(k.last_used_at)}</span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                      {k.scopes.includes("*") ? (
                        <Badge variant="secondary">Full access</Badge>
                      ) : k.scopes.length === 0 ? (
                        <Badge variant="outline">No permissions</Badge>
                      ) : (
                        k.scopes.map((scope) => (
                          <Badge
                            key={scope}
                            variant="outline"
                            className="font-mono text-[11px] font-normal"
                          >
                            {scope}
                          </Badge>
                        ))
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {k.allowed_mailboxes && k.allowed_mailboxes.length > 0
                        ? `Mailboxes: ${k.allowed_mailboxes.join(", ")}`
                        : "All mailboxes"}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                    onClick={() => setRevokeTarget({ id: k.id, name: k.name })}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create API Key Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={handleCloseCreateDialog}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {createdKeyValue ? "API Key Created" : "Create API Key"}
            </DialogTitle>
            <DialogDescription>
              {createdKeyValue
                ? "Copy your API key now. It will not be shown again."
                : "Give your API key a name to help you identify it later."}
            </DialogDescription>
          </DialogHeader>

          {createdKeyValue ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded-md border bg-muted p-3 text-xs font-mono break-all">
                  {createdKeyValue}
                </code>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => handleCopyKey(createdKeyValue)}
                >
                  <Copy className="h-4 w-4" />
                </Button>
              </div>
              <DialogFooter>
                <Button onClick={handleCloseCreateDialog}>Done</Button>
              </DialogFooter>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="key-name">Key Name</Label>
                <Input
                  id="key-name"
                  placeholder="e.g. CI Pipeline, Monitoring"
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label>Access</Label>
                <div className="grid gap-2 sm:grid-cols-2">
                  <button
                    type="button"
                    onClick={() => setAccessMode("full")}
                    className={cn(
                      "rounded-md border p-3 text-left transition-colors",
                      accessMode === "full"
                        ? "border-primary bg-primary/5"
                        : "hover:border-primary/50"
                    )}
                  >
                    <span className="text-sm font-medium">Full access</span>
                    <p className="text-xs text-muted-foreground">
                      Key can use every available scope.
                    </p>
                  </button>
                  <button
                    type="button"
                    onClick={() => setAccessMode("custom")}
                    className={cn(
                      "rounded-md border p-3 text-left transition-colors",
                      accessMode === "custom"
                        ? "border-primary bg-primary/5"
                        : "hover:border-primary/50"
                    )}
                  >
                    <span className="text-sm font-medium">
                      Custom permissions
                    </span>
                    <p className="text-xs text-muted-foreground">
                      Restrict the key to specific scopes.
                    </p>
                  </button>
                </div>
              </div>

              {accessMode === "custom" && (
                <div className="space-y-2">
                  <Label>Permissions</Label>
                  {scopeGroups.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      Loading permissions...
                    </p>
                  ) : (
                    <ScrollArea className="max-h-64 rounded-md border">
                      <div className="space-y-4 p-3">
                        {scopeGroups.map((group) => (
                          <div key={group.group} className="space-y-2">
                            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                              {group.group}
                            </p>
                            <div className="space-y-2">
                              {group.scopes.map((scope) => (
                                <label
                                  key={scope.value}
                                  className="flex cursor-pointer items-start gap-2.5"
                                >
                                  <Checkbox
                                    checked={selectedScopes.has(scope.value)}
                                    onCheckedChange={() =>
                                      toggleScope(scope.value)
                                    }
                                    className="mt-0.5"
                                  />
                                  <span className="space-y-0.5">
                                    <span className="block text-sm leading-none">
                                      {scope.label}
                                    </span>
                                    <span className="block text-xs text-muted-foreground">
                                      {scope.description}
                                    </span>
                                  </span>
                                </label>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </ScrollArea>
                  )}
                  {customWithNoScopes && (
                    <p className="text-xs text-muted-foreground">
                      Select at least one permission.
                    </p>
                  )}
                </div>
              )}

              <div className="space-y-2">
                <Label>Mailboxes</Label>
                <div className="grid gap-2 sm:grid-cols-2">
                  <button
                    type="button"
                    onClick={() => setRestrictMailboxes(false)}
                    className={cn(
                      "rounded-md border p-3 text-left transition-colors",
                      !restrictMailboxes
                        ? "border-primary bg-primary/5"
                        : "hover:border-primary/50"
                    )}
                  >
                    <span className="text-sm font-medium">All my mailboxes</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setRestrictMailboxes(true)}
                    className={cn(
                      "rounded-md border p-3 text-left transition-colors",
                      restrictMailboxes
                        ? "border-primary bg-primary/5"
                        : "hover:border-primary/50"
                    )}
                  >
                    <span className="text-sm font-medium">
                      Limit to specific mailboxes
                    </span>
                  </button>
                </div>
                {restrictMailboxes && (
                  <ScrollArea className="max-h-40 rounded-md border">
                    <div className="space-y-2 p-3">
                      {mailboxes.length === 0 ? (
                        <p className="text-sm text-muted-foreground">
                          No mailboxes available.
                        </p>
                      ) : (
                        mailboxes.map((mb) => (
                          <label
                            key={mb.id}
                            className="flex cursor-pointer items-center gap-2.5"
                          >
                            <Checkbox
                              checked={selectedMailboxes.has(mb.address)}
                              onCheckedChange={() => toggleMailbox(mb.address)}
                            />
                            <span className="text-sm">{mb.address}</span>
                          </label>
                        ))
                      )}
                    </div>
                  </ScrollArea>
                )}
              </div>

              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={handleCloseCreateDialog}
                >
                  Cancel
                </Button>
                <Button
                  onClick={handleCreateKey}
                  disabled={
                    !newKeyName.trim() ||
                    customWithNoScopes ||
                    createKey.isPending
                  }
                >
                  {createKey.isPending && (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  )}
                  Create
                </Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Remove API Key Dialog */}
      <Dialog
        open={revokeTarget !== null}
        onOpenChange={(open) => { if (!open) setRevokeTarget(null); }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove API Key</DialogTitle>
            <DialogDescription>
              Permanently remove <strong>{revokeTarget?.name}</strong>? Any
              applications using this key will lose access immediately. This
              cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRevokeTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleRevoke}
              disabled={revokeKey.isPending}
            >
              {revokeKey.isPending && (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              )}
              Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialogs */}
      <ChangePasswordDialog
        open={changePasswordOpen}
        onOpenChange={setChangePasswordOpen}
      />
      <TOTPSetupDialog
        open={totpSetupOpen}
        onOpenChange={setTotpSetupOpen}
        onSuccess={handleTotpChanged}
      />
      <TOTPDisableDialog
        open={totpDisableOpen}
        onOpenChange={setTotpDisableOpen}
        onSuccess={handleTotpChanged}
      />
    </div>
  );
}

export { ProfilePage };
