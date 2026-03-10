import { useNavigate } from "react-router-dom";
import { useCallback, useEffect } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { LoginForm } from "@/components/auth/login-form";
import { MailCueLogo } from "@/components/mailcue-logo";
import { useAuth } from "@/hooks/use-auth";

function LoginPage() {
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      void navigate("/mail", { replace: true });
    }
  }, [isAuthenticated, navigate]);

  const handleSuccess = useCallback(() => {
    void navigate("/mail", { replace: true });
  }, [navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <div className="w-full max-w-sm space-y-6">
        {/* Branding */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center">
            <MailCueLogo className="h-14 w-14" />
          </div>
          <h1 className="text-2xl font-bold">MailCue</h1>
          <p className="text-sm text-muted-foreground">
            Email Testing Server
          </p>
        </div>

        {/* Login Card */}
        <Card>
          <CardHeader className="text-center">
            <CardTitle className="text-xl">Sign In</CardTitle>
            <CardDescription>
              Enter your credentials to access the mail client
            </CardDescription>
          </CardHeader>
          <CardContent>
            <LoginForm onSuccess={handleSuccess} />
          </CardContent>
        </Card>

        {/* Footer */}
        <p className="text-center text-xs text-muted-foreground">
          by{" "}
          <a
            href="https://www.olib.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-foreground transition-colors"
          >
            Olib AI
          </a>
        </p>
      </div>
    </div>
  );
}

export { LoginPage };
