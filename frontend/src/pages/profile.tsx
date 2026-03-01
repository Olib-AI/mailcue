import { useState } from "react";
import { KeyRound, ShieldCheck, ShieldOff, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/hooks/use-auth";
import { ChangePasswordDialog } from "@/components/auth/change-password-dialog";
import { TOTPSetupDialog } from "@/components/auth/totp-setup-dialog";
import { TOTPDisableDialog } from "@/components/auth/totp-disable-dialog";

function ProfilePage() {
  const { user, refreshUser } = useAuth();
  const [changePasswordOpen, setChangePasswordOpen] = useState(false);
  const [totpSetupOpen, setTotpSetupOpen] = useState(false);
  const [totpDisableOpen, setTotpDisableOpen] = useState(false);

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
