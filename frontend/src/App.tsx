import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { useEffect } from "react";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { AppShell } from "@/components/layout/app-shell";
import { LoginPage } from "@/pages/login";
import { MailPage } from "@/pages/mail";
import { AdminPage } from "@/pages/admin";
import { SettingsPage } from "@/pages/settings";
import { ProfilePage } from "@/pages/profile";
import { DevToolsPage } from "@/pages/dev-tools";
import { MessagingPage } from "@/pages/messaging";
import { HttpBinPage } from "@/pages/http-bin";
import { useAuth } from "@/hooks/use-auth";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

function AuthInitializer({ children }: { children: React.ReactNode }) {
  const { initialize } = useAuth();

  useEffect(() => {
    void initialize();
  }, [initialize]);

  return <>{children}</>;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthInitializer>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<ProtectedRoute />}>
              <Route element={<AppShell />}>
                <Route path="/" element={<Navigate to="/mail" replace />} />
                <Route path="/mail" element={<MailPage />} />
                <Route path="/admin" element={<AdminPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/profile" element={<ProfilePage />} />
                <Route path="/dev-tools" element={<DevToolsPage />} />
                <Route path="/messaging" element={<MessagingPage />} />
                <Route path="/http-bin" element={<HttpBinPage />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/mail" replace />} />
          </Routes>
        </BrowserRouter>
        <Toaster
          position="bottom-right"
          richColors
          closeButton
          toastOptions={{
            duration: 4000,
          }}
        />
      </AuthInitializer>
    </QueryClientProvider>
  );
}

export default App;
