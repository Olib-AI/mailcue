import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useState } from "react";
import { Loader2, Eye, EyeOff, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/use-auth";

const loginSchema = z.object({
  username: z.string().min(1, "Username is required"),
  password: z.string().min(1, "Password is required"),
});

type LoginFormValues = z.infer<typeof loginSchema>;

const totpSchema = z.object({
  code: z
    .string()
    .min(6, "Enter a 6-digit code")
    .max(6, "Enter a 6-digit code")
    .regex(/^\d{6}$/, "Code must be 6 digits"),
});

type TOTPFormValues = z.infer<typeof totpSchema>;

interface LoginFormProps {
  onSuccess: () => void;
}

function LoginForm({ onSuccess }: LoginFormProps) {
  const { login, verify2fa, requires2fa, clear2fa, isLoading, error, clearError } = useAuth();
  const [showPassword, setShowPassword] = useState(false);

  const loginForm = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: "", password: "" },
  });

  const totpForm = useForm<TOTPFormValues>({
    resolver: zodResolver(totpSchema),
    defaultValues: { code: "" },
  });

  const onLoginSubmit = async (data: LoginFormValues) => {
    clearError();
    try {
      await login(data.username, data.password);
      // If no 2FA, login is complete
      if (!useAuth.getState().requires2fa) {
        onSuccess();
      }
    } catch {
      // Error is set in the auth store
    }
  };

  const onTotpSubmit = async (data: TOTPFormValues) => {
    clearError();
    try {
      await verify2fa(data.code);
      onSuccess();
    } catch {
      // Error is set in the auth store
    }
  };

  const handleBack = () => {
    clear2fa();
    totpForm.reset();
  };

  // ── 2FA Code Step ──
  if (requires2fa) {
    return (
      <form onSubmit={totpForm.handleSubmit(onTotpSubmit)} className="space-y-4">
        {error && (
          <div className="rounded-md bg-destructive/10 border border-destructive/20 p-3">
            <p className="text-sm text-destructive">{error}</p>
          </div>
        )}

        <div className="flex flex-col items-center gap-2 text-center">
          <ShieldCheck className="h-8 w-8 text-primary" />
          <p className="text-sm text-muted-foreground">
            Enter the 6-digit code from your authenticator app
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="totp-code">Verification Code</Label>
          <Input
            id="totp-code"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="000000"
            maxLength={6}
            autoFocus
            className="text-center text-lg tracking-widest"
            {...totpForm.register("code")}
          />
          {totpForm.formState.errors.code && (
            <p className="text-xs text-destructive">
              {totpForm.formState.errors.code.message}
            </p>
          )}
        </div>

        <Button type="submit" className="w-full" disabled={isLoading}>
          {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Verify
        </Button>

        <Button
          type="button"
          variant="ghost"
          className="w-full"
          onClick={handleBack}
        >
          Back to login
        </Button>
      </form>
    );
  }

  // ── Username + Password Step ──
  return (
    <form onSubmit={loginForm.handleSubmit(onLoginSubmit)} className="space-y-4">
      {error && (
        <div className="rounded-md bg-destructive/10 border border-destructive/20 p-3">
          <p className="text-sm text-destructive">{error}</p>
        </div>
      )}

      <div className="space-y-1.5">
        <Label htmlFor="username">Username</Label>
        <Input
          id="username"
          type="text"
          placeholder="admin"
          autoComplete="username"
          autoFocus
          {...loginForm.register("username")}
        />
        {loginForm.formState.errors.username && (
          <p className="text-xs text-destructive">
            {loginForm.formState.errors.username.message}
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="password">Password</Label>
        <div className="relative">
          <Input
            id="password"
            type={showPassword ? "text" : "password"}
            placeholder="Enter your password"
            autoComplete="current-password"
            className="pr-10"
            {...loginForm.register("password")}
          />
          <button
            type="button"
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            onClick={() => setShowPassword(!showPassword)}
            aria-label={showPassword ? "Hide password" : "Show password"}
          >
            {showPassword ? (
              <EyeOff className="h-4 w-4" />
            ) : (
              <Eye className="h-4 w-4" />
            )}
          </button>
        </div>
        {loginForm.formState.errors.password && (
          <p className="text-xs text-destructive">
            {loginForm.formState.errors.password.message}
          </p>
        )}
      </div>

      <Button type="submit" className="w-full" disabled={isLoading}>
        {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        Sign In
      </Button>
    </form>
  );
}

export { LoginForm };
