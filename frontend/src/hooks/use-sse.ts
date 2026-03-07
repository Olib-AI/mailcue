import { useEffect, useRef, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { toast } from "sonner";
import { getAccessToken } from "@/lib/api";
import { emailKeys } from "./use-emails";
import { mailboxKeys } from "./use-mailboxes";
import type { EmailReceivedEvent } from "@/types/api";

const SSE_URL = "/api/v1/events/stream";

/**
 * Hook that maintains an SSE connection for real-time event updates.
 * Invalidates TanStack Query caches on relevant events and shows
 * toast notifications for new emails.
 */
export function useSSE(enabled: boolean): void {
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  const connect = useCallback(() => {
    // Abort any existing connection
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    const token = getAccessToken();

    void fetchEventSource(SSE_URL, {
      signal: ctrl.signal,
      headers: token ? { Authorization: `Bearer ${token}` } : {},

      onmessage(event) {
        switch (event.event) {
          case "email.received": {
            void queryClient.invalidateQueries({
              queryKey: emailKeys.lists(),
            });
            void queryClient.invalidateQueries({
              queryKey: mailboxKeys.list(),
            });
            try {
              const data = JSON.parse(event.data) as EmailReceivedEvent;
              toast.info("New email received", {
                description: `From: ${data.from} — ${data.subject}`,
              });
            } catch {
              // Data parse failure is non-critical
            }
            break;
          }
          case "email.deleted": {
            void queryClient.invalidateQueries({
              queryKey: emailKeys.lists(),
            });
            void queryClient.invalidateQueries({
              queryKey: mailboxKeys.list(),
            });
            break;
          }
          case "mailbox.created":
          case "mailbox.deleted": {
            void queryClient.invalidateQueries({
              queryKey: mailboxKeys.list(),
            });
            break;
          }
          case "heartbeat":
            // Connection keepalive — no action needed
            break;
        }
      },

      onerror(err) {
        // Log and let fetchEventSource handle reconnection
        console.warn("[SSE] Connection error, will retry:", err);
      },

      openWhenHidden: true,
    });
  }, [queryClient]);

  useEffect(() => {
    if (!enabled) return;

    connect();

    return () => {
      abortRef.current?.abort();
    };
  }, [enabled, connect]);
}
