import { Outlet } from "react-router-dom";
import { Sidebar } from "./sidebar";
import { Header } from "./header";
import { ComposeDialog } from "@/components/email/compose-dialog";
import { useSSE } from "@/hooks/use-sse";
import { useAuth } from "@/hooks/use-auth";

function AppShell() {
  const { isAuthenticated } = useAuth();

  // Maintain SSE connection while authenticated
  useSSE(isAuthenticated);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header />
        <main className="flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
      <ComposeDialog />
    </div>
  );
}

export { AppShell };
