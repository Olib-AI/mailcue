import { useNavigate, useLocation } from "react-router-dom";
import {
  Inbox,
  Send,
  FileText,
  Trash2,
  Settings,
  Syringe,
  ChevronLeft,
  ChevronRight,
  Mail,
  Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { useUIStore } from "@/stores/ui-store";
import { useMailboxes } from "@/hooks/use-mailboxes";
import type { FolderName } from "@/types/api";

const FOLDER_ICONS: Record<FolderName, typeof Inbox> = {
  INBOX: Inbox,
  Sent: Send,
  Drafts: FileText,
  Trash: Trash2,
};

const FOLDER_LABELS: Record<FolderName, string> = {
  INBOX: "Inbox",
  Sent: "Sent",
  Drafts: "Drafts",
  Trash: "Trash",
};

const FOLDERS: FolderName[] = ["INBOX", "Sent", "Drafts", "Trash"];

function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    sidebarCollapsed,
    toggleSidebar,
    selectedMailbox,
    setSelectedMailbox,
    selectedFolder,
    setSelectedFolder,
  } = useUIStore();

  const { data: mailboxData, isLoading: mailboxesLoading } = useMailboxes();
  const mailboxes = mailboxData?.mailboxes ?? [];

  const isAdminPage = location.pathname.startsWith("/admin");

  // Auto-select first mailbox if none selected
  if (!selectedMailbox && mailboxes.length > 0 && mailboxes[0]) {
    setSelectedMailbox(mailboxes[0].address);
  }

  const handleFolderClick = (folder: FolderName) => {
    setSelectedFolder(folder);
    if (location.pathname !== "/mail") {
      void navigate("/mail");
    }
  };

  const handleMailboxClick = (address: string) => {
    setSelectedMailbox(address);
    setSelectedFolder("INBOX");
    if (location.pathname !== "/mail") {
      void navigate("/mail");
    }
  };

  return (
    <aside
      className={cn(
        "flex flex-col border-r bg-sidebar text-sidebar-foreground transition-all duration-200",
        sidebarCollapsed ? "w-14" : "w-60"
      )}
    >
      {/* Logo / Brand */}
      <div className="flex h-14 items-center justify-between border-b px-3">
        {!sidebarCollapsed && (
          <div className="flex items-center gap-2">
            <Mail className="h-5 w-5 text-primary" />
            <span className="font-semibold text-lg">MailCue</span>
          </div>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleSidebar}
          className="h-8 w-8 shrink-0"
          aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {sidebarCollapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </Button>
      </div>

      <ScrollArea className="flex-1 py-2">
        {/* Folders */}
        <div className="px-2 space-y-0.5">
          {FOLDERS.map((folder) => {
            const Icon = FOLDER_ICONS[folder];
            const isActive = selectedFolder === folder && !isAdminPage;
            const selectedMb = mailboxes.find(
              (m) => m.address === selectedMailbox
            );
            const unreadCount =
              folder === "INBOX" ? (selectedMb?.unread_count ?? 0) : 0;

            return (
              <button
                key={folder}
                type="button"
                onClick={() => handleFolderClick(folder)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {!sidebarCollapsed && (
                  <>
                    <span className="flex-1 text-left">
                      {FOLDER_LABELS[folder]}
                    </span>
                    {unreadCount > 0 && (
                      <span className="text-xs font-semibold text-primary">
                        {unreadCount}
                      </span>
                    )}
                  </>
                )}
              </button>
            );
          })}
        </div>

        <Separator className="my-3 mx-2" />

        {/* Mailboxes */}
        {!sidebarCollapsed && (
          <div className="px-2">
            <div className="flex items-center justify-between px-2.5 mb-1">
              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Mailboxes
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5"
                onClick={() => void navigate("/admin")}
                aria-label="Add mailbox"
              >
                <Plus className="h-3 w-3" />
              </Button>
            </div>

            {mailboxesLoading ? (
              <div className="space-y-1">
                <Skeleton className="h-7 w-full" />
                <Skeleton className="h-7 w-full" />
                <Skeleton className="h-7 w-3/4" />
              </div>
            ) : (
              <div className="space-y-0.5">
                {mailboxes.map((mailbox) => (
                  <button
                    key={mailbox.address}
                    type="button"
                    onClick={() => handleMailboxClick(mailbox.address)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors",
                      selectedMailbox === mailbox.address
                        ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                        : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                    )}
                  >
                    <Mail className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{mailbox.address}</span>
                    {mailbox.unread_count > 0 && (
                      <span className="ml-auto text-xs font-semibold text-primary">
                        {mailbox.unread_count}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <Separator className="my-3 mx-2" />

        {/* Admin Links */}
        <div className="px-2 space-y-0.5">
          {!sidebarCollapsed && (
            <span className="px-2.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Admin
            </span>
          )}
          <button
            type="button"
            onClick={() => void navigate("/admin")}
            className={cn(
              "flex w-full items-center gap-3 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors mt-1",
              isAdminPage && !location.pathname.includes("inject")
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
            )}
          >
            <Settings className="h-4 w-4 shrink-0" />
            {!sidebarCollapsed && <span>Mailboxes</span>}
          </button>
          <button
            type="button"
            onClick={() => void navigate("/admin?tab=inject")}
            className={cn(
              "flex w-full items-center gap-3 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
              location.pathname.includes("inject") ||
                (isAdminPage && location.search.includes("inject"))
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
            )}
          >
            <Syringe className="h-4 w-4 shrink-0" />
            {!sidebarCollapsed && <span>Inject Email</span>}
          </button>
        </div>
      </ScrollArea>
    </aside>
  );
}

export { Sidebar };
