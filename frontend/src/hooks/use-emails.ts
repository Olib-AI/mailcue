import {
  useQuery,
  useMutation,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import { api } from "@/lib/api";
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
  return useQuery({
    queryKey: emailKeys.detail(mailbox ?? "", uid ?? ""),
    queryFn: () =>
      api.get<EmailDetail>(
        `/mailboxes/${encodeURIComponent(mailbox ?? "")}/emails/${encodeURIComponent(uid ?? "")}`
      ),
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
    },
  });
}

export function useDeleteEmail() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      mailbox,
      uid,
    }: {
      mailbox: string;
      uid: string;
    }) => api.delete<void>(`/mailboxes/${encodeURIComponent(mailbox)}/emails/${encodeURIComponent(uid)}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: emailKeys.lists() });
    },
  });
}
