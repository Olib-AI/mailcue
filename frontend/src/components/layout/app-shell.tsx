import { useState, useCallback } from "react";
import { Outlet } from "react-router-dom";
import { X } from "lucide-react";
import { Sidebar } from "./sidebar";
import { Header } from "./header";
import { ComposeDialog } from "@/components/email/compose-dialog";
import { CompareBar } from "@/components/email/compare-bar";
import { CompareView } from "@/components/email/compare-view";
import { KeyboardShortcutsDialog } from "@/components/keyboard-shortcuts-dialog";
import { Button } from "@/components/ui/button";
import { useSSE } from "@/hooks/use-sse";
import { useAuth } from "@/hooks/use-auth";
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts";

function AppShell() {
  const { isAuthenticated } = useAuth();
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

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
      {/* Desktop sidebar — always visible */}
      <div className="hidden md:flex">
        <Sidebar onOpenShortcuts={() => setShortcutsOpen(true)} />
      </div>

      {/* Mobile sidebar overlay */}
      {mobileSidebarOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/50"
            onClick={() => setMobileSidebarOpen(false)}
            aria-hidden="true"
          />
          {/* Sidebar panel */}
          <div className="relative z-50 flex">
            <Sidebar
              onOpenShortcuts={() => {
                setShortcutsOpen(true);
                setMobileSidebarOpen(false);
              }}
            />
            <Button
              variant="ghost"
              size="icon"
              className="absolute top-3 right-[-40px] h-8 w-8 text-white hover:bg-white/20"
              onClick={() => setMobileSidebarOpen(false)}
              aria-label="Close sidebar"
            >
              <X className="h-5 w-5" />
            </Button>
          </div>
        </div>
      )}

      <div className="flex flex-1 flex-col overflow-hidden">
        <Header
          onMobileMenuToggle={() => setMobileSidebarOpen(true)}
        />
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
      <ComposeDialog />
      <CompareBar />
      <CompareView />
      <KeyboardShortcutsDialog
        open={shortcutsOpen}
        onOpenChange={setShortcutsOpen}
      />
    </div>
  );
}

export { AppShell };
