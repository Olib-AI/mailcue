import { useState, useCallback } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./sidebar";
import { Header } from "./header";
import { ComposeDialog } from "@/components/email/compose-dialog";
import { KeyboardShortcutsDialog } from "@/components/keyboard-shortcuts-dialog";
import { useSSE } from "@/hooks/use-sse";
import { useAuth } from "@/hooks/use-auth";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";

function AppShell() {
  const { isAuthenticated } = useAuth();
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  const handleSetShortcutsOpen = useCallback((open: boolean) => {
    setShortcutsOpen(open);
  }, []);

  // Maintain SSE connection while authenticated
  useSSE(isAuthenticated);

  // Register global keyboard shortcuts
  useKeyboardShortcuts({
    shortcutsDialogOpen: shortcutsOpen,
    setShortcutsDialogOpen: handleSetShortcutsOpen,
  });

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar onOpenShortcuts={() => setShortcutsOpen(true)} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header />
        <main className="flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
      <ComposeDialog />
      <KeyboardShortcutsDialog
        open={shortcutsOpen}
        onOpenChange={setShortcutsOpen}
      />
    </div>
  );
}

export { AppShell };
