import { create } from "zustand";
import type { EmailDetail as EmailDetailType } from "@/types/api";

type Theme = "light" | "dark" | "system";

type ComposeMode = "new" | "reply" | "reply-all" | "forward";

interface ComposeContext {
  mode: ComposeMode;
  originalEmail: EmailDetailType;
}

function getSystemTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "system";
  const stored = localStorage.getItem("mailcue-theme");
  if (stored === "light" || stored === "dark" || stored === "system") {
    return stored;
  }
  return "system";
}

function applyTheme(theme: Theme): void {
  const resolved = theme === "system" ? getSystemTheme() : theme;
  document.documentElement.classList.toggle("dark", resolved === "dark");
}

interface UIState {
  // Sidebar
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;

  // Selected email
  selectedEmailUid: string | null;
  setSelectedEmailUid: (uid: string | null) => void;

  // Selected mailbox
  selectedMailbox: string | null;
  setSelectedMailbox: (mailbox: string | null) => void;

  // Selected folder
  selectedFolder: string;
  setSelectedFolder: (folder: string) => void;

  // Compose dialog
  composeOpen: boolean;
  composeContext: ComposeContext | null;
  setComposeOpen: (open: boolean) => void;
  openCompose: (context?: ComposeContext) => void;

  // Theme
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

export const useUIStore = create<UIState>((set) => {
  // Apply initial theme on store creation
  const initialTheme = getInitialTheme();
  applyTheme(initialTheme);

  // Listen for system theme changes
  if (typeof window !== "undefined") {
    window
      .matchMedia("(prefers-color-scheme: dark)")
      .addEventListener("change", () => {
        const currentTheme = useUIStore.getState().theme;
        if (currentTheme === "system") {
          applyTheme("system");
        }
      });
  }

  return {
    sidebarCollapsed: false,
    toggleSidebar: () =>
      set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
    setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

    selectedEmailUid: null,
    setSelectedEmailUid: (uid) => set({ selectedEmailUid: uid }),

    selectedMailbox: null,
    setSelectedMailbox: (mailbox) =>
      set({ selectedMailbox: mailbox, selectedEmailUid: null }),

    selectedFolder: "INBOX",
    setSelectedFolder: (folder) =>
      set({ selectedFolder: folder, selectedEmailUid: null }),

    composeOpen: false,
    composeContext: null,
    setComposeOpen: (open) =>
      set({ composeOpen: open, ...(!open && { composeContext: null }) }),
    openCompose: (context) =>
      set({ composeOpen: true, composeContext: context ?? null }),

    theme: initialTheme,
    setTheme: (theme) => {
      localStorage.setItem("mailcue-theme", theme);
      applyTheme(theme);
      set({ theme });
    },
  };
});
