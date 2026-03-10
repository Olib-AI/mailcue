import { useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { toast } from "sonner";
import { useUIStore } from "@/stores/ui-store";
import { useDeleteEmail, emailKeys } from "@/hooks/use-emails";
import type { EmailListResponse } from "@/types/api";

/**
 * Returns true when the keyboard event originates from an element
 * where single-character shortcuts should be suppressed (inputs,
 * textareas, contenteditable, or select elements).
 */
function isEditableTarget(event: KeyboardEvent): boolean {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return false;

  const tagName = target.tagName;
  if (
    tagName === "INPUT" ||
    tagName === "TEXTAREA" ||
    tagName === "SELECT"
  ) {
    return true;
  }

  if (target.isContentEditable) return true;

  return false;
}

interface KeyboardShortcutsOptions {
  shortcutsDialogOpen: boolean;
  setShortcutsDialogOpen: (open: boolean) => void;
}

function useKeyboardShortcuts({
  shortcutsDialogOpen,
  setShortcutsDialogOpen,
}: KeyboardShortcutsOptions): void {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const deleteEmail = useDeleteEmail();

  // Track pending "g" prefix for two-key sequences
  const pendingGRef = useRef(false);
  const pendingGTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearPendingG = useCallback(() => {
    pendingGRef.current = false;
    if (pendingGTimerRef.current !== null) {
      clearTimeout(pendingGTimerRef.current);
      pendingGTimerRef.current = null;
    }
  }, []);

  /**
   * Read the current email UID list from the React Query cache.
   * This avoids prop-drilling or extra subscriptions -- we read
   * synchronously from the cache using the current store state.
   */
  const getEmailUids = useCallback((): string[] => {
    const { selectedMailbox, selectedFolder } = useUIStore.getState();
    if (!selectedMailbox) return [];

    // Match any search variant for the current mailbox+folder.
    // The list query key is: ["emails", "list", mailbox, folder, search]
    const queries = queryClient.getQueriesData<InfiniteData<EmailListResponse>>({
      queryKey: emailKeys.list(selectedMailbox, selectedFolder),
    });

    // Take the first matching query's infinite data and flatten all pages
    for (const [, data] of queries) {
      if (data?.pages) {
        return data.pages.flatMap((page) => page.emails.map((e) => e.uid));
      }
    }

    return [];
  }, [queryClient]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      // Never intercept when a modifier key (Ctrl/Cmd/Alt) is held,
      // except for the Delete key which has no character conflict.
      if (
        (event.ctrlKey || event.metaKey || event.altKey) &&
        event.key !== "Delete"
      ) {
        return;
      }

      const editable = isEditableTarget(event);

      // --- Two-key sequence: "g" prefix handling ---
      if (pendingGRef.current) {
        clearPendingG();

        // These work even in editable? No -- skip if editable.
        if (editable) return;

        const store = useUIStore.getState();

        if (event.key === "i") {
          event.preventDefault();
          store.setSelectedFolder("INBOX");
          navigate("/mail");
          return;
        }

        if (event.key === "s") {
          event.preventDefault();
          store.setSelectedFolder("Sent");
          navigate("/mail");
          return;
        }

        // Unknown second key -- ignore
        return;
      }

      // --- Escape: always active (works inside dialogs too) ---
      if (event.key === "Escape") {
        const store = useUIStore.getState();

        // Priority 1: close shortcuts dialog
        if (shortcutsDialogOpen) {
          event.preventDefault();
          setShortcutsDialogOpen(false);
          return;
        }

        // Priority 2: close compose dialog
        if (store.composeOpen) {
          // The Dialog component already handles Escape internally,
          // so we do NOT preventDefault here -- let it bubble.
          return;
        }

        // Priority 3: deselect email
        if (store.selectedEmailUid !== null) {
          event.preventDefault();
          store.setSelectedEmailUid(null);
          return;
        }

        return;
      }

      // --- All remaining shortcuts require non-editable focus ---
      if (editable) return;

      const store = useUIStore.getState();

      switch (event.key) {
        // Compose
        case "c": {
          event.preventDefault();
          store.setComposeOpen(true);
          return;
        }

        // Navigate down
        case "j":
        case "ArrowDown": {
          event.preventDefault();
          const uids = getEmailUids();
          if (uids.length === 0) return;

          const currentIdx = store.selectedEmailUid
            ? uids.indexOf(store.selectedEmailUid)
            : -1;
          const nextIdx = currentIdx + 1;
          const nextUid = uids[nextIdx];
          if (nextUid !== undefined) {
            store.setSelectedEmailUid(nextUid);
          } else if (currentIdx === -1) {
            // Nothing selected -- select first
            const firstUid = uids[0];
            if (firstUid !== undefined) {
              store.setSelectedEmailUid(firstUid);
            }
          }
          return;
        }

        // Navigate up
        case "k":
        case "ArrowUp": {
          event.preventDefault();
          const uids = getEmailUids();
          if (uids.length === 0) return;

          const currentIdx = store.selectedEmailUid
            ? uids.indexOf(store.selectedEmailUid)
            : -1;
          if (currentIdx > 0) {
            const prevUid = uids[currentIdx - 1];
            if (prevUid !== undefined) {
              store.setSelectedEmailUid(prevUid);
            }
          }
          return;
        }

        // Open selected email (Enter / o)
        case "Enter":
        case "o": {
          // Enter and o just confirm the selection -- the detail pane
          // already reacts to selectedEmailUid changes. Nothing extra needed.
          return;
        }

        // Delete selected email
        case "d":
        case "Delete": {
          if (!store.selectedEmailUid || !store.selectedMailbox) return;
          event.preventDefault();

          const uidToDelete = store.selectedEmailUid;
          const mailbox = store.selectedMailbox;
          const folder = store.selectedFolder;

          // Move selection to next email before deleting
          const uids = getEmailUids();
          const idx = uids.indexOf(uidToDelete);
          const nextUid = uids[idx + 1] ?? uids[idx - 1] ?? null;

          deleteEmail.mutate(
            { mailbox, uid: uidToDelete, folder },
            {
              onSuccess: () => {
                toast.success(
                  folder.toLowerCase() === "trash"
                    ? "Email permanently deleted"
                    : "Email moved to Trash"
                );
                store.setSelectedEmailUid(nextUid);
              },
              onError: (err) => {
                toast.error(
                  err instanceof Error
                    ? err.message
                    : "Failed to delete email"
                );
              },
            }
          );
          return;
        }

        // Focus search
        case "/": {
          event.preventDefault();
          const searchInput = document.querySelector<HTMLInputElement>(
            "[data-search-input]"
          );
          if (searchInput) {
            searchInput.focus();
          }
          return;
        }

        // Toggle shortcuts help
        case "?": {
          event.preventDefault();
          setShortcutsDialogOpen(!shortcutsDialogOpen);
          return;
        }

        // Start "go to" sequence
        case "g": {
          event.preventDefault();
          pendingGRef.current = true;
          pendingGTimerRef.current = setTimeout(() => {
            pendingGRef.current = false;
            pendingGTimerRef.current = null;
          }, 500);
          return;
        }

        default:
          break;
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      clearPendingG();
    };
  }, [
    navigate,
    queryClient,
    deleteEmail,
    getEmailUids,
    shortcutsDialogOpen,
    setShortcutsDialogOpen,
    clearPendingG,
  ]);
}

export { useKeyboardShortcuts };
