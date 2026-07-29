import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  CreateWarmupAccountRequest,
  CreateWarmupCampaignRequest,
  WarmupAccount,
  WarmupCampaign,
  WarmupEvent,
  WarmupProviderState,
} from "@/types/api";

const keys = {
  all: ["warmup"] as const,
  accounts: ["warmup", "accounts"] as const,
  campaigns: ["warmup", "campaigns"] as const,
  events: ["warmup", "events"] as const,
  providers: ["warmup", "provider-states"] as const,
};

export function useWarmupAccounts() {
  return useQuery({ queryKey: keys.accounts, queryFn: () => api.get<WarmupAccount[]>("/warmup/accounts") });
}

export function useWarmupCampaigns() {
  return useQuery({
    queryKey: keys.campaigns,
    queryFn: () => api.get<WarmupCampaign[]>("/warmup/campaigns"),
    refetchInterval: 15_000,
  });
}

export function useWarmupEvents(limit: number = 5) {
  return useQuery({
    queryKey: [...keys.events, limit],
    queryFn: () => api.get<WarmupEvent[]>(`/warmup/events?limit=${limit}`),
    refetchInterval: 15_000,
  });
}

export function useWarmupProviderStates() {
  return useQuery({
    queryKey: keys.providers,
    queryFn: () => api.get<WarmupProviderState[]>("/warmup/provider-states"),
    refetchInterval: 15_000,
  });
}

export function useResumeWarmupProvider() {
  const invalidate = useInvalidateWarmup();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<WarmupProviderState>(`/warmup/provider-states/${id}/resume`, {}),
    onSuccess: invalidate,
  });
}

function useInvalidateWarmup() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: keys.all });
}

export function useCreateWarmupAccount() {
  const invalidate = useInvalidateWarmup();
  return useMutation({ mutationFn: (body: CreateWarmupAccountRequest) => api.post<WarmupAccount>("/warmup/accounts", body), onSuccess: invalidate });
}

export function useCheckWarmupAccount() {
  const invalidate = useInvalidateWarmup();
  return useMutation({ mutationFn: (id: string) => api.post<{ ok: boolean; message: string }>(`/warmup/accounts/${id}/check`, {}), onSuccess: invalidate });
}

export function useToggleWarmupAccount() {
  const invalidate = useInvalidateWarmup();
  return useMutation({ mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.patch<WarmupAccount>(`/warmup/accounts/${id}`, { enabled }), onSuccess: invalidate });
}

export function useDeleteWarmupAccount() {
  const invalidate = useInvalidateWarmup();
  return useMutation({ mutationFn: (id: string) => api.delete<void>(`/warmup/accounts/${id}`), onSuccess: invalidate });
}

export function useCreateWarmupCampaign() {
  const invalidate = useInvalidateWarmup();
  return useMutation({ mutationFn: (body: CreateWarmupCampaignRequest) => api.post<WarmupCampaign>("/warmup/campaigns", body), onSuccess: invalidate });
}

export function useUpdateWarmupCampaign() {
  const invalidate = useInvalidateWarmup();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: CreateWarmupCampaignRequest }) =>
      api.put<WarmupCampaign>(`/warmup/campaigns/${id}`, body),
    onSuccess: invalidate,
  });
}

export function useControlWarmupCampaign() {
  const invalidate = useInvalidateWarmup();
  return useMutation({ mutationFn: ({ id, action }: { id: string; action: "start" | "pause" | "stop" }) => api.post<WarmupCampaign>(`/warmup/campaigns/${id}/${action}`, {}), onSuccess: invalidate });
}

export function useClearWarmupMailbox() {
  const invalidate = useInvalidateWarmup();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<{ ok: boolean; deleted_count: number }>(`/warmup/campaigns/${id}/clear-mailbox`, {}),
    onSuccess: invalidate,
  });
}
