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
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/hooks/use-api-keys";
import { ChangePasswordDialog } from "@/components/auth/change-password-dialog";
import { TOTPSetupDialog } from "@/components/auth/totp-setup-dialog";
import { TOTPDisableDialog } from "@/components/auth/totp-disable-dialog";
import { formatEmailDate } from "@/lib/utils";

function ProfilePage() {
  const { user, refreshUser } = useAuth();
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);
  const [totpSetupOpen, setTotpSetupOpen] = useState(false);
  const [totpDisableOpen, setTotpDisableOpen] = useState(false);

  // API Keys
  const { data: apiKeys, isLoading: keysLoading } = useApiKeys();
  const createKey = useCreateApiKey();
  const revokeKey = useRevokeApiKey();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [createdKeyValue, setCreatedKeyValue] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<{ id: string; name: string } | null>(null);

  const handleCreateKey = () => {
    if (!newKeyName.trim()) return;
    createKey.mutate(
      { name: newKeyName.trim() },
      {
        onSuccess: (result) => {
          setCreatedKeyValue(result.key);
          setNewKeyName("");
        },
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : "Failed to create API key"
          );
        },
      }
    );
  };

  const handleCloseCreateDialog = () => {
    setCreateDialogOpen(false);
    setCreatedKeyValue(null);
    setNewKeyName("");
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
        toast.success(`API key "${revokeTarget.name}" revoked`);
        setRevokeTarget(null);
      },
      onError: (err) => {
        toast.error(
          err instanceof Error ? err.message : "Failed to revoke API key"
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
                  className="flex items-center justify-between rounded-md border p-3"
                >
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{k.name}</span>
                      {!k.is_active && (
                        <Badge variant="secondary" className="text-xs">
                          Revoked
                        </Badge>
                      )}
                    </div>
                    <div className="flex gap-3 text-xs text-muted-foreground">
                      <span>
                        Prefix: <code className="bg-muted px-1 rounded">{k.prefix}...</code>
                      </span>
                      <span>Created {formatEmailDate(k.created_at)}</span>
                      {k.last_used_at && (
                        <span>Last used {formatEmailDate(k.last_used_at)}</span>
                      )}
                    </div>
                  </div>
                  {k.is_active && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      onClick={() => setRevokeTarget({ id: k.id, name: k.name })}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create API Key Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={handleCloseCreateDialog}>
        <DialogContent>
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
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleCreateKey();
                  }}
                />
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
                  disabled={!newKeyName.trim() || createKey.isPending}
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

      {/* Revoke API Key Dialog */}
      <Dialog
        open={revokeTarget !== null}
        onOpenChange={(open) => { if (!open) setRevokeTarget(null); }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke API Key</DialogTitle>
            <DialogDescription>
              Are you sure you want to revoke{" "}
              <strong>{revokeTarget?.name}</strong>? Any applications using this
              key will lose access immediately.
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
              Revoke
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
