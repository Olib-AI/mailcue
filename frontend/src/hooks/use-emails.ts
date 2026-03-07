import {
  useQuery,
  useMutation,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import { api } from "@/lib/api";
import { mailboxKeys } from "./use-mailboxes";
import type {
  EmailListResponse,
  EmailDetail,
  SendEmailRequest,
  InjectEmailRequest,
} from "@/types/api";

// --- Query Keys ---

export const emailKeys = {
  all: ["emails"] as const,
  lists: () => [...emailKeys.all, "list"] as const,
  list: (mailbox: string, folder: string, page: number, search?: string) =>
    [...emailKeys.lists(), mailbox, folder, page, search ?? ""] as const,
  details: () => [...emailKeys.all, "detail"] as const,
  detail: (mailbox: string, uid: string) =>
    [...emailKeys.details(), mailbox, uid] as const,
};

// --- Hooks ---

export function useEmails(
  mailbox: string | null,
  folder: string,
  page: number = 1,
  search?: string
) {
  return useQuery({
    queryKey: emailKeys.list(mailbox ?? "", folder, page, search),
    queryFn: () => {
      const params = new URLSearchParams({
        folder,
        page: String(page),
        page_size: "50",
      });
      if (search) params.set("search", search);
      return api.get<EmailListResponse>(
        `/mailboxes/${encodeURIComponent(mailbox ?? "")}/emails?${params.toString()}`
      );
    },
    enabled: !!mailbox,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useEmail(mailbox: string | null, uid: string | null) {
  const queryClient = useQueryClient();

  return useQuery({
    queryKey: emailKeys.detail(mailbox ?? "", uid ?? ""),
    queryFn: async () => {
      const detail = await api.get<EmailDetail>(
        `/mailboxes/${encodeURIComponent(mailbox ?? "")}/emails/${encodeURIComponent(uid ?? "")}`
      );
      // Backend marks email as read (\Seen) on fetch — update the list cache
      // so the unread indicator disappears immediately without a full refetch.
      queryClient.setQueriesData<EmailListResponse>(
        { queryKey: emailKeys.lists() },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            emails: old.emails.map((e) =>
              e.uid === uid ? { ...e, is_read: true } : e
            ),
          };
        }
      );
      // Also refresh mailbox counts (unread_count changed)
      void queryClient.invalidateQueries({ queryKey: mailboxKeys.list() });
      return detail;
    },
    enabled: !!mailbox && uid !== null,
    staleTime: 60_000,
  });
}

export function useSendEmail() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: SendEmailRequest) =>
      api.post<{ message_id: string }>("/emails/send", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: emailKeys.lists() });
      void queryClient.invalidateQueries({ queryKey: mailboxKeys.list() });
    },
  });
}

export function useInjectEmail() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: InjectEmailRequest) =>
      api.post<{ uid: string }>("/emails/inject", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: emailKeys.lists() });
      void queryClient.invalidateQueries({ queryKey: mailboxKeys.list() });
    },
  });
}

export function useDeleteEmail() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      mailbox,
      uid,
      folder = "INBOX",
    }: {
      mailbox: string;
      uid: string;
      folder?: string;
    }) => api.delete<void>(`/mailboxes/${encodeURIComponent(mailbox)}/emails/${encodeURIComponent(uid)}?folder=${encodeURIComponent(folder)}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: emailKeys.lists() });
      void queryClient.invalidateQueries({ queryKey: mailboxKeys.list() });
    },
  });
}

export function useBulkDeleteEmails() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      mailbox,
      uids,
      folder = "INBOX",
    }: {
      mailbox: string;
      uids: string[];
      folder?: string;
    }) =>
      api.post<{ deleted: number; failed: number }>(
        `/mailboxes/${encodeURIComponent(mailbox)}/emails/bulk-delete?folder=${encodeURIComponent(folder)}`,
        { uids }
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: emailKeys.lists() });
      void queryClient.invalidateQueries({ queryKey: mailboxKeys.list() });
    },
  });
}
