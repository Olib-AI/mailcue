import {
  useQuery,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { InfiniteData } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { mailboxKeys } from "./use-mailboxes";
import type {
  EmailListResponse,
  EmailDetail,
  SendEmailRequest,
  InjectEmailRequest,
  UpdateFlagsRequest,
} from "@/types/api";

// --- Query Keys ---

export const emailKeys = {
  all: ["emails"] as const,
  lists: () => [...emailKeys.all, "list"] as const,
  list: (mailbox: string, folder: string, search?: string) =>
    [...emailKeys.lists(), mailbox, folder, search ?? ""] as const,
  details: () => [...emailKeys.all, "detail"] as const,
  detail: (mailbox: string, uid: string) =>
    [...emailKeys.details(), mailbox, uid] as const,
};

// --- Constants ---

const PAGE_SIZE = 50;

// --- Hooks ---

export function useEmails(
  mailbox: string | null,
  folder: string,
  search?: string
) {
  return useInfiniteQuery({
    queryKey: emailKeys.list(mailbox ?? "", folder, search),
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({
        folder,
        page: String(pageParam),
        page_size: String(PAGE_SIZE),
      });
      if (search) params.set("search", search);
      return api.get<EmailListResponse>(
        `/mailboxes/${encodeURIComponent(mailbox ?? "")}/emails?${params.toString()}`
      );
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.page + 1 : undefined,
    enabled: !!mailbox,
    staleTime: 30_000,
  });
}

export function useEmail(mailbox: string | null, uid: string | null, folder: string = "INBOX") {
  const queryClient = useQueryClient();

  return useQuery({
    queryKey: emailKeys.detail(mailbox ?? "", uid ?? ""),
    queryFn: async () => {
      const params = new URLSearchParams({ folder });
      const detail = await api.get<EmailDetail>(
        `/mailboxes/${encodeURIComponent(mailbox ?? "")}/emails/${encodeURIComponent(uid ?? "")}?${params.toString()}`
      );
      // Backend marks email as read (\Seen) on fetch — update the list cache
      // so the unread indicator disappears immediately without a full refetch.
      queryClient.setQueriesData<InfiniteData<EmailListResponse>>(
        { queryKey: emailKeys.lists() },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            pages: old.pages.map((page) => ({
              ...page,
              emails: page.emails.map((e) =>
                e.uid === uid ? { ...e, is_read: true } : e
              ),
            })),
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

export function useToggleReadStatus() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      mailbox,
      uid,
      seen,
    }: {
      mailbox: string;
      uid: string;
      seen: boolean;
    }) =>
      api.patch<void>(
        `/mailboxes/${encodeURIComponent(mailbox)}/emails/${encodeURIComponent(uid)}/flags`,
        { seen } satisfies UpdateFlagsRequest
      ),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: emailKeys.lists() });
      void queryClient.invalidateQueries({
        queryKey: emailKeys.detail(variables.mailbox, variables.uid),
      });
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
