import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  MailboxListResponse,
  CreateMailboxRequest,
  Mailbox,
} from "@/types/api";

export const mailboxKeys = {
  all: ["mailboxes"] as const,
  list: () => [...mailboxKeys.all, "list"] as const,
};

export function useMailboxes() {
  return useQuery({
    queryKey: mailboxKeys.list(),
    queryFn: () => api.get<MailboxListResponse>("/mailboxes"),
    staleTime: 10_000,
  });
}

export function useCreateMailbox() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateMailboxRequest) =>
      api.post<{ address: string }>("/mailboxes", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: mailboxKeys.list() });
    },
  });
}

export function useDeleteMailbox() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (address: string) =>
      api.delete<void>(`/mailboxes/${encodeURIComponent(address)}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: mailboxKeys.list() });
    },
  });
}

export function usePurgeMailbox() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (address: string) =>
      api.post<{ deleted: number }>(
        `/mailboxes/${encodeURIComponent(address)}/purge`
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: mailboxKeys.list() });
    },
  });
}

export function useUpdateSignature() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      address,
      signature,
    }: {
      address: string;
      signature: string;
    }) =>
      api.put<Mailbox>(
        `/mailboxes/${encodeURIComponent(address)}/signature`,
        { signature }
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: mailboxKeys.list() });
    },
  });
}
